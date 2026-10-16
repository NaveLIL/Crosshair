//! Executes the existing UI on an explicitly synthetic QEMU display/input BSP.
#![no_std]
#![no_main]

#[path = "arch/mod.rs"]
mod arch;
#[path = "drivers/pxa_uart.rs"]
mod pxa_uart;

use core::{
    arch::asm,
    mem::size_of,
    panic::PanicInfo,
    ptr::{addr_of_mut, read_volatile, write_volatile},
};
use crosshair_ui::{
    MAX_PIXELS, Surface,
    components::{AppsScreen, Event, Focus, InputQueue, View},
};

const DISPLAY: usize = 0x1000_0000;
const INPUT: usize = 0x1000_1000;
const MAGIC: u32 = 0x4453_504c;
const PREFIX: u32 = 0xc17e_0000;
const SUFFIX: u32 = 0xf00d_0000;

// Stable u32 diagnostic ABI, published with STAGE=2 after each complete event.
#[unsafe(no_mangle)]
static mut CROSSHAIR_DISPLAY_RECORD: [u32; 32] = [0; 32];

#[repr(C, align(8))]
struct GuardedFramebuffer {
    before: [u32; 16],
    pixels: [u16; MAX_PIXELS],
    after: [u32; 16],
}
#[unsafe(no_mangle)]
static mut DISPLAY_FRAMEBUFFER: GuardedFramebuffer = GuardedFramebuffer {
    before: [0; 16],
    pixels: [0; MAX_PIXELS],
    after: [0; 16],
};
#[unsafe(no_mangle)]
static mut DISPLAY_SENTINEL: [u32; 64] = [0; 64];

unsafe fn read(address: usize) -> u32 {
    // SAFETY: private callers use aligned mapped synthetic registers or own RAM.
    unsafe { read_volatile(address as *const u32) }
}
unsafe fn write(address: usize, value: u32) {
    // SAFETY: single privileged test CPU, no IRQ/DMA or physical device access.
    unsafe { write_volatile(address as *mut u32, value) }
}
unsafe fn record(index: usize, value: u32) {
    // SAFETY: fixed indices below32, aligned volatile publication, no references.
    unsafe {
        write_volatile(
            addr_of_mut!(CROSSHAIR_DISPLAY_RECORD)
                .cast::<u32>()
                .add(index),
            value,
        )
    }
}

fn decode(wire: u32) -> Event {
    let scalar = wire & 0x00ff_ffff;
    assert!(wire >> 24 == 8 || scalar == 0);
    match wire >> 24 {
        1 => Event::Up,
        2 => Event::Down,
        3 => Event::Left,
        4 => Event::Right,
        5 => Event::Select,
        6 => Event::Back,
        7 => Event::Menu,
        8 => Event::TextInput(char::from_u32(scalar).expect("input scalar")),
        _ => panic!("invalid test input encoding"),
    }
}

unsafe fn guards() {
    // SAFETY: guards are disjoint from the exclusively borrowed pixel slice.
    // No shared reference to the mutable framebuffer or sentinel is formed.
    unsafe {
        for i in 0..16 {
            assert!(
                read(
                    addr_of_mut!(DISPLAY_FRAMEBUFFER.before)
                        .cast::<u32>()
                        .add(i) as usize
                ) == PREFIX ^ i as u32
            );
            assert!(
                read(addr_of_mut!(DISPLAY_FRAMEBUFFER.after).cast::<u32>().add(i) as usize)
                    == SUFFIX ^ i as u32
            );
        }
        for i in 0..64 {
            assert!(
                read(addr_of_mut!(DISPLAY_SENTINEL).cast::<u32>().add(i) as usize)
                    == 0x51a7_0000 ^ i as u32
            );
        }
    }
}

unsafe fn render(app: &AppsScreen, surface: &mut Surface<'_>, frames: &mut u32) {
    app.render(surface); // The same library function as the host fixture.
    assert!(surface.dirty_rects().len() == 1);
    // SAFETY: the validated display range points to this one exclusive pixel
    // buffer; PRESENT synchronously copies it. No autonomous framebuffer DMA.
    let count = surface
        .present(|rect, pixels, stride| {
            assert!(rect.right() <= 240 && rect.bottom() <= 320);
            assert!(pixels.len() == MAX_PIXELS && stride == 240);
            // Publish ordinary pixel stores before the MMIO copy command. This is
            // a compiler barrier; cache/DMA hardware coherency is not being modeled.
            // Omit `nomem`/`readonly`: this empty asm is a compiler memory clobber.
            // The pinned ARMv5 LLVM lowers compiler_fence to unavailable
            // __sync_synchronize; no fake runtime barrier is supplied here.
            unsafe {
                asm!("", options(nostack, preserves_flags));
            }
            unsafe {
                write(DISPLAY + 0x14, 1);
            }
            Ok::<(), ()>(())
        })
        .expect("present");
    *frames += 1;
    assert!(surface.dirty_rects().is_empty());
    // SAFETY: only this guest writes PRESENT while the integration test runs.
    unsafe {
        assert!(read(DISPLAY + 0x14) == *frames);
        record(21, count as u32);
        record(22, surface.dirty_rects().len() as u32);
    }
}

unsafe fn publish(app: &AppsScreen, events: u32, frames: u32) {
    // SAFETY: IRQ/FIQ masked, one writer. Stage is published last; host pauses
    // the CPU after seeing its requested event count before inspecting state.
    unsafe {
        guards();
        record(3, events);
        record(4, frames);
        record(10, 1);
        record(
            13,
            match app.view() {
                View::List => 0,
                View::Action(i) => 0x100 | i as u32,
                View::Menu => 2,
            },
        );
        record(
            14,
            match app.focus() {
                Focus::List => 0,
                Focus::LeftSoftkey => 1,
                Focus::RightSoftkey => 2,
            },
        );
        record(15, app.selected_item().map_or(u32::MAX, |i| i as u32));
        record(16, app.scroll() as u32);
        record(17, app.match_count() as u32);
        record(18, app.filter().len() as u32);
        record(19, app.opened_count() as u32);
        record(20, read(DISPLAY + 0x14));
        record(23, 1);
        let sp: u32;
        asm!("mov {sp}, sp", sp=out(reg) sp, options(nostack, nomem));
        record(24, sp);
        record(1, 2);
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_main() -> ! {
    // SAFETY: reused ARM entry cleared BSS, set aligned stacks, masked IRQ/FIQ;
    // this binary is restricted to the named synthetic display-test machine.
    unsafe {
        let rec = addr_of_mut!(CROSSHAIR_DISPLAY_RECORD).cast::<u32>() as usize;
        assert!(read(rec + 4) == 0);
        record(0, MAGIC);
        record(1, 1);
        let mut uart = pxa_uart::ReferenceUart::init();
        let midr: u32;
        let control: u32;
        asm!("mrc p15, 0, {r}, c0, c0, 0", r=out(reg) midr, options(nostack, nomem));
        asm!("mrc p15, 0, {r}, c1, c0, 0", r=out(reg) control, options(nostack, nomem));
        assert!(midr == 0x6905_2903 && control == 0x78);
        record(25, midr);
        record(26, control);
        assert!(read(DISPLAY + 4) == 240 && read(DISPLAY + 8) == 320);
        assert!(read(DISPLAY + 0xc) == 480 && read(DISPLAY + 0x10) == 0x565);
        assert!(read(DISPLAY) == 0 && read(DISPLAY + 0x14) == 0);
        assert!(read(INPUT) == 0 && read(INPUT + 0xc) == 8 && read(INPUT + 0x10) == 0);
        for i in 0..16 {
            write_volatile(
                addr_of_mut!(DISPLAY_FRAMEBUFFER.before)
                    .cast::<u32>()
                    .add(i),
                PREFIX ^ i as u32,
            );
            write_volatile(
                addr_of_mut!(DISPLAY_FRAMEBUFFER.after).cast::<u32>().add(i),
                SUFFIX ^ i as u32,
            );
        }
        for i in 0..64 {
            write_volatile(
                addr_of_mut!(DISPLAY_SENTINEL).cast::<u32>().add(i),
                0x51a7_0000 ^ i as u32,
            );
        }
        let pixel_ptr = addr_of_mut!(DISPLAY_FRAMEBUFFER.pixels).cast::<u16>();
        write(DISPLAY, pixel_ptr as u32);
        record(5, pixel_ptr as u32);
        record(6, (MAX_PIXELS * 2) as u32);
        record(7, 240);
        record(8, 320);
        record(9, 240);
        record(27, size_of::<AppsScreen>() as u32);
        record(28, size_of::<InputQueue>() as u32);
        record(29, size_of::<Surface<'_>>() as u32);
        // SAFETY: exactly the pixel field of our static RAM allocation, one
        // mutable borrow for its lifetime; guards are outside this slice.
        let pixels = core::slice::from_raw_parts_mut(pixel_ptr, MAX_PIXELS);
        let mut surface = Surface::new(pixels, 240, 320, 240).expect("framebuffer");
        let mut app = AppsScreen::new();
        let mut queue = InputQueue::new();
        let mut events = 0;
        let mut frames = 0;
        render(&app, &mut surface, &mut frames);
        publish(&app, events, frames);
        assert!(uart.send("CROSSHAIR DISPLAY TEST — UI READY\r\n").is_ok());
        loop {
            if read(INPUT) == 0 {
                core::hint::spin_loop();
                continue;
            }
            record(1, 3);
            while queue.len() < 8 && read(INPUT) != 0 {
                let event = decode(read(INPUT + 4));
                assert!(queue.push(event).is_ok());
            }
            while let Some(event) = queue.pop() {
                // Every event invalidates the previous published snapshot,
                // including subsequent events drained from the same burst.
                record(1, 3);
                let changed = app.handle(event);
                if changed {
                    render(&app, &mut surface, &mut frames);
                }
                events += 1;
                // Recover the wire value without leaking compiler enum layout.
                record(
                    11,
                    match event {
                        Event::Up => 1 << 24,
                        Event::Down => 2 << 24,
                        Event::Left => 3 << 24,
                        Event::Right => 4 << 24,
                        Event::Select => 5 << 24,
                        Event::Back => 6 << 24,
                        Event::Menu => 7 << 24,
                        Event::TextInput(c) => (8 << 24) | c as u32,
                    },
                );
                record(12, changed as u32);
                publish(&app, events, frames);
            }
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn rust_irq() {
    panic!("unexpected IRQ");
}
#[unsafe(no_mangle)]
pub extern "C" fn rust_fault(kind: u32, lr: u32, psr: u32) -> ! {
    // SAFETY: terminal fault wrapper restored SVC stack; own RAM remains mapped.
    unsafe {
        record(2, kind);
        record(30, lr);
        record(31, psr);
        record(1, 0xff);
    }
    arch::idle()
}
#[panic_handler]
fn panic(_: &PanicInfo<'_>) -> ! {
    // SAFETY: deterministic terminal failure in synthetic MMU/cache-off guest.
    unsafe {
        record(2, 0xdead);
        record(1, 0xff);
    }
    arch::idle()
}
