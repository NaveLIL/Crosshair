//! Unprivileged Shell entry/ABI adapter; no MMIO or kernel pointers.
#![no_std]
#![no_main]
use core::{
    arch::{asm, global_asm},
    panic::PanicInfo,
    ptr::{addr_of, addr_of_mut, read_volatile, write_volatile},
};
use crosshair_shell::{Action, BuildInfo, RuntimeInfo, Shell, Snapshot};
use crosshair_ui::{MAX_PIXELS, Surface, components::Event};
global_asm!(
    r#"
.syntax unified
.arch armv5te
.arm
.section .text.user_entry,"ax",%progbits
.global user_start
user_start:
    ldr r0,=__user_bss_start
    ldr r1,=__user_bss_end
    mov r2,#0
1:  cmp r0,r1
    strlo r2,[r0],#4
    blo 1b
    bl shell_user_main
    b .
.global shell_svc
shell_svc:
    stmdb sp!,{r4,r7,r12,lr}
    mov r7,r0
    mov r0,r1
    mov r1,r2
    mov r2,r3
    ldr r3,[sp,#16]
    svc #0
    ldmia sp!,{r4,r7,r12,lr}
    bx lr
.ltorg
"#,
    options(raw)
);
unsafe extern "C" {
    fn shell_svc(n: u32, a: u32, b: u32, c: u32, d: u32) -> u32;
}
const FB: u32 = 0x01010040;
const BYTES: u32 = 153600;
#[repr(C, align(8))]
struct Framebuffer {
    before: [u32; 16],
    pixels: [u16; MAX_PIXELS],
    after: [u32; 16],
}
#[unsafe(no_mangle)]
#[unsafe(link_section = ".user.framebuffer")]
static mut SHELL_FRAMEBUFFER: Framebuffer = Framebuffer {
    before: [0; 16],
    pixels: [0; MAX_PIXELS],
    after: [0; 16],
};
#[unsafe(no_mangle)]
static mut SHELL_USER_RECORD: [u32; 44] = [0; 44];
#[unsafe(no_mangle)]
static mut SHELL_METRICS: [u32; 12] = [0; 12];
#[unsafe(no_mangle)]
static mut SHELL_TRACE: [u32; 32 * 64] = [0; 32 * 64];
/// Last render's bounded work counters, not a second frame or a kernel ABI.
#[unsafe(no_mangle)]
static mut SHELL_RENDER_METRICS: [u32; 8] = [0; 8];
unsafe fn call(n: u32, a: u32, b: u32, c: u32, d: u32) -> u32 {
    // SAFETY: assembly follows AAPCS, saves r4/r7/LR, SVC is the only privilege
    // boundary. Kernel validates all raw arguments; no references span copyout.
    unsafe { shell_svc(n, a, b, c, d) }
}
fn decode(w: u32) -> Action {
    // The unchanged synthetic FIFO accepts logical keys and Unicode only.
    // Supplementary private-use scalars transport a synthetic tap. The host
    // reserves this range from text; Shell rejects coordinates beyond 240x320.
    // This is an emulator adapter convention, not a Blue Angel sensor protocol.
    if w >> 24 == 8 {
        let scalar = w & 0xffffff;
        if (0x0f0000..=0x10ffff).contains(&scalar) {
            let packed = scalar - 0x0f0000;
            return Action::Pointer {
                x: (packed & 0xff) as u16,
                y: (packed >> 8) as u16,
            };
        }
    }
    Action::Key(match w >> 24 {
        1 => Event::Up,
        2 => Event::Down,
        3 => Event::Left,
        4 => Event::Right,
        5 => Event::Select,
        6 => Event::Back,
        7 => Event::Menu,
        8 => Event::TextInput(char::from_u32(w & 0xffffff).unwrap_or('\u{fffd}')),
        _ => Event::TextInput('\0'),
    })
}
unsafe fn metrics() -> RuntimeInfo {
    // SAFETY: fixed exclusive own User data allocation, exact48B ABI.
    unsafe {
        assert!(call(4, addr_of_mut!(SHELL_METRICS) as u32, 48, 0, 0) == 48);
        read_volatile(addr_of_mut!(SHELL_METRICS).cast::<RuntimeInfo>())
    }
}
#[unsafe(no_mangle)]
pub extern "C" fn shell_user_main() -> ! {
    // SAFETY: initial User entry owns BSS/stack/framebuffer; single Shell
    // writer. PRESENT is synchronous and no User rendering races kernel read.
    unsafe {
        for i in 0..16 {
            write_volatile(
                addr_of_mut!(SHELL_FRAMEBUFFER.before).cast::<u32>().add(i),
                0xface7000 ^ i as u32,
            );
            write_volatile(
                addr_of_mut!(SHELL_FRAMEBUFFER.after).cast::<u32>().add(i),
                0xbeef7000 ^ i as u32,
            );
        }
        let probes = [
            call(3, 0xa0008000, BYTES, 0, 320 << 16 | 240),
            call(3, 0xfffffff0, BYTES, 0, 320 << 16 | 240),
            call(3, FB, BYTES - 1, 0, 320 << 16 | 240),
            call(3, FB, BYTES, 1, 320 << 16 | 240),
            call(3, FB, BYTES, 0, 0),
            call(4, 0xa0008000, 48, 0, 0),
            call(4, addr_of_mut!(SHELL_METRICS) as u32, 47, 0, 0),
            call(4, 0xfffffff0, 48, 0, 0),
            call(99, 0, 0, 0, 0),
            call(1, 0x01000000, 4, 0, 0),
            call(1, 0x01010000, 65, 0, 0),
            call(2, 0, 0, 0, 0),
        ];
        for (i, v) in probes.iter().enumerate() {
            write_volatile(
                addr_of_mut!(SHELL_USER_RECORD).cast::<u32>().add(32 + i),
                *v,
            );
        }
        let pixels = core::slice::from_raw_parts_mut(
            addr_of_mut!(SHELL_FRAMEBUFFER.pixels).cast::<u16>(),
            MAX_PIXELS,
        );
        let mut surface = Surface::new(pixels, 240, 320, 240).unwrap();
        let mut shell = Shell::new(BuildInfo {
            version: "0.1.1 / Wave007.1",
            architecture: "ARMv5TE",
            environment: "QEMU synthetic",
        });
        let mut wire = 0;
        loop {
            let runtime = metrics();
            shell.update_runtime(runtime);
            if wire != 0 {
                shell.handle(decode(wire));
            }
            let rendered = shell.render(&mut surface);
            let render_metrics = shell.render_stats().words();
            // SAFETY: fixed exclusive own User data; host observation only.
            core::ptr::copy_nonoverlapping(
                render_metrics.as_ptr(),
                addr_of_mut!(SHELL_RENDER_METRICS).cast::<u32>(),
                8,
            );
            if rendered {
                // The current broker publishes the entire fixed framebuffer.
                // Surface may report several disjoint dirty rectangles, but
                // one full publication already covers all of them. Keep the
                // renderer API and its retry semantics; do not copy pixels.
                let mut published = false;
                surface
                    .present(|_, _, _| {
                        if published {
                            return Ok(());
                        }
                        // Compiler memory clobber publishes pixel stores before SVC.
                        asm!("", options(nostack, preserves_flags));
                        let result = call(3, FB, BYTES, 0, 320 << 16 | 240);
                        if result == 0 {
                            published = true;
                            Ok(())
                        } else {
                            Err(())
                        }
                    })
                    .unwrap();
            }
            let snapshot = shell.snapshot();
            const _: () = assert!(core::mem::size_of::<Snapshot>() == 64);
            const _: () = assert!(core::mem::size_of::<RuntimeInfo>() == 48);
            let record = addr_of_mut!(SHELL_USER_RECORD).cast::<u32>();
            write_volatile(record, 0x5553484c);
            write_volatile(record.add(1), 1);
            write_volatile(record.add(2), 1);
            write_volatile(record.add(3), wire);
            core::ptr::copy_nonoverlapping(addr_of!(snapshot).cast::<u32>(), record.add(4), 16);
            core::ptr::copy_nonoverlapping(addr_of!(runtime).cast::<u32>(), record.add(20), 12);
            write_volatile(record.add(2), 2);
            let slot = snapshot.events_processed as usize % 64;
            core::ptr::copy_nonoverlapping(
                record,
                addr_of_mut!(SHELL_TRACE).cast::<u32>().add(slot * 32),
                32,
            );
            wire = call(5, 0, 0, 0, 0);
        }
    }
}
#[panic_handler]
fn panic(_: &PanicInfo<'_>) -> ! {
    // SAFETY: report failure only in our own memory then Exit current task.
    unsafe {
        write_volatile(addr_of_mut!(SHELL_USER_RECORD).cast::<u32>().add(2), 0xff);
        call(0, 0xdead, 0, 0, 0);
    }
    loop {
        core::hint::spin_loop()
    }
}
