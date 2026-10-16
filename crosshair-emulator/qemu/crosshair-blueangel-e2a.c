/*
 * SPDX-License-Identifier: GPL-2.0-only
 * Crosshair E2A: deliberately incomplete, synthetic Blue Angel experiment.
 *
 * Timer/PIC layout and interrupt-update structure derived from QEMU 9.1.0:
 * hw/timer/pxa2xx_timer.c and hw/arm/pxa2xx_pic.c.
 * Copyright (c) 2006 Openedhand Ltd.
 * Copyright (c) 2006 Thorsten Zitterell
 * Original PIC written by Andrzej Zaborowski <balrog@zabor.org>.
 * New E2A implementation and integration: Project Crosshair contributors.
 * See this directory's README.md and COPYING.GPL-2.0 for provenance/terms.
 *
 * This is host emulator code. It is not part of the MIT Rust guest kernel.
 * No flash, modem, LCD, GPIO, power or storage model is provided.
 */
#include "qemu/osdep.h"
#include "qemu/units.h"
#include "qemu/module.h"
#include "qemu/timer.h"
#include "qemu/log.h"
#include "qemu/error-report.h"
#include "qapi/error.h"
#include "hw/boards.h"
#include "hw/sysbus.h"
#include "hw/irq.h"
#include "hw/qdev-properties.h"
#include "hw/char/serial.h"
#include "exec/address-spaces.h"
#include "migration/vmstate.h"
#include "sysemu/sysemu.h"
#include "target/arm/cpu.h"

#define TYPE_CROSSHAIR_E2A_IO "crosshair-e2a-io"
OBJECT_DECLARE_SIMPLE_TYPE(CrosshairE2AState, CROSSHAIR_E2A_IO)

#define E2A_FREQ 3686400U
#define E2A_RAM_BASE 0xa0000000ULL
#define E2A_RAM_SIZE (128 * MiB)
#define E2A_TIMER_BASE 0x40a00000ULL
#define E2A_PIC_BASE 0x40d00000ULL
#define E2A_UART_BASE 0x40100000ULL
#define E2A_TIMER_IRQ_FIRST 26
#define E2A_UART_IRQ 22
#define E2A_IO_SIZE 0x1000

typedef struct CrosshairE2ATimer {
    QEMUTimer *timer;
    CrosshairE2AState *owner;
    unsigned channel;
} CrosshairE2ATimer;

struct CrosshairE2AState {
    SysBusDevice parent_obj;
    MemoryRegion timer_region;
    MemoryRegion pic_region;
    MemoryRegion uart_region;
    SerialState uart;
    qemu_irq uart_input;
    qemu_irq output[2]; /* sysbus-irq 0=IRQ, 1=FIQ */
    CrosshairE2ATimer channels[4];
    int64_t epoch_ns;
    uint32_t counter_base;
    uint32_t match[4];
    uint32_t events;
    uint32_t enabled;
    uint32_t pending;
    uint32_t mask;
    uint32_t route_fiq;
};

static uint32_t e2a_counter(CrosshairE2AState *s, int64_t now)
{
    uint64_t elapsed = now >= s->epoch_ns ? now - s->epoch_ns : 0;
    return s->counter_base + muldiv64(elapsed, E2A_FREQ,
                                      NANOSECONDS_PER_SECOND);
}

static void e2a_update_irq(CrosshairE2AState *s)
{
    uint32_t timer_bits = 0xfU << E2A_TIMER_IRQ_FIRST;
    uint32_t active;

    s->pending = (s->pending & ~timer_bits) |
                 ((s->events & 0xf) << E2A_TIMER_IRQ_FIRST);
    active = s->pending & s->mask;
    qemu_set_irq(s->output[0], (active & ~s->route_fiq) != 0);
    qemu_set_irq(s->output[1], (active & s->route_fiq) != 0);
}

static void e2a_schedule(CrosshairE2AState *s, unsigned channel)
{
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    uint64_t elapsed = now >= s->epoch_ns ? now - s->epoch_ns : 0;
    uint64_t elapsed_ticks = muldiv64(elapsed, E2A_FREQ,
                                       NANOSECONDS_PER_SECOND);
    uint64_t delta = (uint32_t)(s->match[channel] -
                               e2a_counter(s, now));
    uint64_t target_tick, deadline_delta;

    /* Equality denotes the next wrap, avoiding repeated callbacks at now. */
    if (delta == 0) {
        delta = 1ULL << 32;
    }
    target_tick = elapsed_ticks + delta;
    deadline_delta = muldiv64(target_tick, NANOSECONDS_PER_SECOND, E2A_FREQ);
    /* Round the edge up: the counter must actually reach the match tick. */
    if (muldiv64(deadline_delta, E2A_FREQ, NANOSECONDS_PER_SECOND) <
        target_tick) {
        deadline_delta++;
    }
    timer_mod(s->channels[channel].timer, s->epoch_ns + deadline_delta);
}

static void e2a_schedule_all(CrosshairE2AState *s)
{
    unsigned i;
    for (i = 0; i < 4; i++) {
        e2a_schedule(s, i);
    }
}

static void e2a_tick(void *opaque)
{
    CrosshairE2ATimer *channel = opaque;
    CrosshairE2AState *s = channel->owner;

    /* PXA26x documented match gating: a disabled match does not latch. */
    if (s->enabled & (1U << channel->channel)) {
        s->events |= 1U << channel->channel;
    }
    e2a_update_irq(s);
    e2a_schedule(s, channel->channel);
}

static MemTxResult e2a_bad_access(const char *region, hwaddr addr,
                                 unsigned size, bool write)
{
    qemu_log_mask(LOG_GUEST_ERROR,
                  "crosshair-e2a: rejected %s %s offset=0x%" HWADDR_PRIx
                  " size=%u\n", region, write ? "write" : "read", addr, size);
    return MEMTX_ERROR;
}

static MemTxResult e2a_timer_read(void *opaque, hwaddr addr, uint64_t *data,
                                unsigned size, MemTxAttrs attrs)
{
    CrosshairE2AState *s = opaque;
    *data = 0;
    if (size != 4 || (addr & 3)) {
        return e2a_bad_access("timer", addr, size, false);
    }
    if (addr <= 0x0c) {
        *data = s->match[addr >> 2];
        return MEMTX_OK;
    }
    switch (addr) {
    case 0x10:
        *data = e2a_counter(s, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
        break;
    case 0x14:
        *data = s->events;
        break;
    case 0x1c:
        *data = s->enabled;
        break;
    default:
        return e2a_bad_access("timer", addr, size, false);
    }
    return MEMTX_OK;
}

static MemTxResult e2a_timer_write(void *opaque, hwaddr addr, uint64_t data,
                                 unsigned size, MemTxAttrs attrs)
{
    CrosshairE2AState *s = opaque;
    if (size != 4 || (addr & 3)) {
        return e2a_bad_access("timer", addr, size, true);
    }
    if (addr <= 0x0c) {
        s->match[addr >> 2] = data;
        e2a_schedule(s, addr >> 2);
        return MEMTX_OK;
    }
    switch (addr) {
    case 0x10:
        s->counter_base = data;
        s->epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        e2a_schedule_all(s);
        break;
    case 0x14:
        s->events &= ~(data & 0xf);
        e2a_update_irq(s);
        break;
    case 0x1c:
        s->enabled = data & 0xf;
        e2a_update_irq(s);
        break;
    default:
        return e2a_bad_access("timer", addr, size, true);
    }
    return MEMTX_OK;
}

static MemTxResult e2a_pic_read(void *opaque, hwaddr addr, uint64_t *data,
                              unsigned size, MemTxAttrs attrs)
{
    CrosshairE2AState *s = opaque;
    *data = 0;
    if (size != 4 || (addr & 3)) {
        return e2a_bad_access("pic", addr, size, false);
    }
    switch (addr) {
    case 0x00:
        *data = s->pending & s->mask & ~s->route_fiq;
        break;
    case 0x04:
        *data = s->mask;
        break;
    case 0x08:
        *data = s->route_fiq;
        break;
    case 0x0c:
        *data = s->pending & s->mask & s->route_fiq;
        break;
    case 0x10:
        *data = s->pending;
        break;
    default:
        return e2a_bad_access("pic", addr, size, false);
    }
    return MEMTX_OK;
}

static MemTxResult e2a_pic_write(void *opaque, hwaddr addr, uint64_t data,
                               unsigned size, MemTxAttrs attrs)
{
    CrosshairE2AState *s = opaque;
    if (size != 4 || (addr & 3)) {
        return e2a_bad_access("pic", addr, size, true);
    }
    switch (addr) {
    case 0x04:
        s->mask = data;
        break;
    case 0x08:
        s->route_fiq = data;
        break;
    default:
        return e2a_bad_access("pic", addr, size, true);
    }
    e2a_update_irq(s);
    return MEMTX_OK;
}

static MemTxResult e2a_uart_read(void *opaque, hwaddr addr, uint64_t *data,
                               unsigned size, MemTxAttrs attrs)
{
    CrosshairE2AState *s = opaque;
    *data = 0;
    if ((size != 1 && size != 4) || (addr & 3) || addr > 0x1c) {
        return e2a_bad_access("diagnostic-uart", addr, size, false);
    }
    *data = serial_io_ops.read(&s->uart, addr >> 2, 1);
    return MEMTX_OK;
}

static MemTxResult e2a_uart_write(void *opaque, hwaddr addr, uint64_t data,
                                unsigned size, MemTxAttrs attrs)
{
    CrosshairE2AState *s = opaque;
    if ((size != 1 && size != 4) || (addr & 3) || addr > 0x1c ||
        addr == 0x14 || addr == 0x18) {
        return e2a_bad_access("diagnostic-uart", addr, size, true);
    }
    serial_io_ops.write(&s->uart, addr >> 2, data & 0xff, 1);
    return MEMTX_OK;
}

/* Let all normal MMIO widths reach the attrs callbacks. They reject bad
 * widths themselves with MEMTX_ERROR, without splitting them into valid
 * smaller writes that could mutate state before a failure. */
#define E2A_ACCESS_OPS(READ, WRITE) { \
    .read_with_attrs = READ, .write_with_attrs = WRITE, \
    .endianness = DEVICE_LITTLE_ENDIAN, \
    .valid = { .min_access_size = 1, .max_access_size = 8, .unaligned = true }, \
    .impl = { .min_access_size = 1, .max_access_size = 8, .unaligned = true }, \
}

static const MemoryRegionOps e2a_timer_ops =
    E2A_ACCESS_OPS(e2a_timer_read, e2a_timer_write);
static const MemoryRegionOps e2a_pic_ops =
    E2A_ACCESS_OPS(e2a_pic_read, e2a_pic_write);
static const MemoryRegionOps e2a_uart_ops =
    E2A_ACCESS_OPS(e2a_uart_read, e2a_uart_write);

static void e2a_uart_irq(void *opaque, int number, int level)
{
    CrosshairE2AState *s = opaque;
    if (level) {
        s->pending |= 1U << E2A_UART_IRQ;
    } else {
        s->pending &= ~(1U << E2A_UART_IRQ);
    }
    e2a_update_irq(s);
}

static void e2a_reset_hold(Object *obj, ResetType type)
{
    CrosshairE2AState *s = CROSSHAIR_E2A_IO(obj);
    unsigned i;

    s->epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    s->counter_base = 0;
    s->events = s->enabled = s->pending = s->mask = s->route_fiq = 0;
    for (i = 0; i < 4; i++) {
        timer_del(s->channels[i].timer);
        s->match[i] = 0;
    }
    e2a_update_irq(s);
    e2a_schedule_all(s);
}

static void e2a_realize(DeviceState *dev, Error **errp)
{
    CrosshairE2AState *s = CROSSHAIR_E2A_IO(dev);
    s->uart_input = qemu_allocate_irq(e2a_uart_irq, s, 0);
    s->uart.irq = s->uart_input;
    qdev_prop_set_uint32(DEVICE(&s->uart), "baudbase", 14745600 / 16);
    if (!qdev_realize(DEVICE(&s->uart), NULL, errp)) {
        qemu_free_irq(s->uart_input);
        s->uart_input = NULL;
    }
}

static void e2a_unrealize(DeviceState *dev)
{
    CrosshairE2AState *s = CROSSHAIR_E2A_IO(dev);
    qdev_unrealize(DEVICE(&s->uart));
    qemu_free_irq(s->uart_input);
    s->uart_input = NULL;
}

static void e2a_instance_init(Object *obj)
{
    CrosshairE2AState *s = CROSSHAIR_E2A_IO(obj);
    SysBusDevice *bus = SYS_BUS_DEVICE(obj);
    unsigned i;

    object_initialize_child(obj, "uart", &s->uart, TYPE_SERIAL);
    memory_region_init_io(&s->timer_region, obj, &e2a_timer_ops, s,
                          "crosshair-e2a.timer", E2A_IO_SIZE);
    memory_region_init_io(&s->pic_region, obj, &e2a_pic_ops, s,
                          "crosshair-e2a.pic", E2A_IO_SIZE);
    memory_region_init_io(&s->uart_region, obj, &e2a_uart_ops, s,
                          "crosshair-e2a.diagnostic-uart", E2A_IO_SIZE);
    sysbus_init_mmio(bus, &s->timer_region);
    sysbus_init_mmio(bus, &s->pic_region);
    sysbus_init_mmio(bus, &s->uart_region);
    sysbus_init_irq(bus, &s->output[0]);
    sysbus_init_irq(bus, &s->output[1]);
    for (i = 0; i < 4; i++) {
        s->channels[i].owner = s;
        s->channels[i].channel = i;
        s->channels[i].timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, e2a_tick,
                                           &s->channels[i]);
    }
}

static void e2a_instance_finalize(Object *obj)
{
    CrosshairE2AState *s = CROSSHAIR_E2A_IO(obj);
    unsigned i;
    for (i = 0; i < 4; i++) {
        timer_free(s->channels[i].timer);
    }
}

static void e2a_class_init(ObjectClass *klass, void *data)
{
    static const VMStateDescription no_migration = {
        .name = "crosshair-e2a", .unmigratable = true,
    };
    DeviceClass *dc = DEVICE_CLASS(klass);
    ResettableClass *rc = RESETTABLE_CLASS(klass);
    dc->desc = "Crosshair E2A synthetic timer/PIC and test-only UART";
    dc->user_creatable = false;
    dc->realize = e2a_realize;
    dc->unrealize = e2a_unrealize;
    dc->vmsd = &no_migration;
    rc->phases.hold = e2a_reset_hold;
}

static void crosshair_e2a_init(MachineState *machine)
{
    ARMCPU *cpu;
    DeviceState *dev;
    CrosshairE2AState *io;
    MemoryRegion *vectors;

    if (machine->ram_size != E2A_RAM_SIZE) {
        error_report("crosshair-blueangel-e2a requires exactly 128 MiB RAM");
        exit(1);
    }
    if (machine->kernel_filename) {
        error_report("E2A uses -device loader,file=<own ELF>,cpu-num=0; -kernel is unsupported");
        exit(1);
    }
    cpu = ARM_CPU(object_new(machine->cpu_type));
    object_property_add_child(OBJECT(machine), "cpu", OBJECT(cpu));
    qdev_realize_and_unref(DEVICE(cpu), NULL, &error_fatal);
    memory_region_add_subregion(get_system_memory(), E2A_RAM_BASE, machine->ram);

    /* Synthetic 64-byte low-vector scratch RAM. No flash alias or real
     * Blue Angel SRAM claim. RAM intentionally persists across warm reset. */
    vectors = g_new(MemoryRegion, 1);
    /* Migratable RAM helpers require a DeviceState owner (or NULL), while
     * MachineState is only an Object. The address-space owns this region. */
    memory_region_init_ram(vectors, NULL, "crosshair-e2a.vectors",
                           64, &error_fatal);
    memory_region_add_subregion(get_system_memory(), 0, vectors);

    dev = qdev_new(TYPE_CROSSHAIR_E2A_IO);
    object_property_add_child(OBJECT(machine), "e2a", OBJECT(dev));
    io = CROSSHAIR_E2A_IO(dev);
    if (serial_hd(0)) {
        qdev_prop_set_chr(DEVICE(&io->uart), "chardev", serial_hd(0));
    }
    sysbus_realize_and_unref(SYS_BUS_DEVICE(dev), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(dev), 0, E2A_TIMER_BASE);
    sysbus_mmio_map(SYS_BUS_DEVICE(dev), 1, E2A_PIC_BASE);
    sysbus_mmio_map(SYS_BUS_DEVICE(dev), 2, E2A_UART_BASE);
    sysbus_connect_irq(SYS_BUS_DEVICE(dev), 0,
                        qdev_get_gpio_in(DEVICE(cpu), ARM_CPU_IRQ));
    sysbus_connect_irq(SYS_BUS_DEVICE(dev), 1,
                        qdev_get_gpio_in(DEVICE(cpu), ARM_CPU_FIQ));
}

static void crosshair_e2a_machine_class_init(MachineClass *mc)
{
    static const char * const cpu_types[] = {
        ARM_CPU_TYPE_NAME("pxa260"), ARM_CPU_TYPE_NAME("pxa255"), NULL,
    };
    mc->desc = "Crosshair Blue Angel E2A (synthetic, incomplete, experimental PXA26x proxy)";
    mc->init = crosshair_e2a_init;
    mc->default_cpu_type = ARM_CPU_TYPE_NAME("pxa260");
    mc->valid_cpu_types = cpu_types;
    mc->default_ram_size = E2A_RAM_SIZE;
    mc->default_ram_id = "crosshair-e2a.ram";
    mc->max_cpus = 1;
    mc->ignore_memory_transaction_failures = false;
}

static const TypeInfo e2a_io_type = {
    .name = TYPE_CROSSHAIR_E2A_IO,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(CrosshairE2AState),
    .instance_init = e2a_instance_init,
    .instance_finalize = e2a_instance_finalize,
    .class_init = e2a_class_init,
};

static void e2a_register_types(void)
{
    type_register_static(&e2a_io_type);
}
type_init(e2a_register_types)
DEFINE_MACHINE("crosshair-blueangel-e2a", crosshair_e2a_machine_class_init)
