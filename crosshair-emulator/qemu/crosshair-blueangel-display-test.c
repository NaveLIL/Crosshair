/*
 * SPDX-License-Identifier: GPL-2.0-only
 * Crosshair Wave004 synthetic display and logical-input test devices.
 * Copyright Project Crosshair contributors.
 *
 * This is a new test protocol, NOT an ATI W3200/LCD/keyboard/touch model.
 * QEMU graphical-console APIs are from pinned QEMU 9.2 ui/console.c and
 * include/ui/{console,surface}.h. No vendor driver is copied here.
 * Only this TU is compiled; the unchanged E2B/E2A units register all boards.
 */
#include "crosshair-blueangel-e2b.c"
#include "ui/console.h"
#include "qemu/bswap.h"

#define TYPE_CROSSHAIR_TEST_DISPLAY "crosshair-test-display"
#define TYPE_CROSSHAIR_LOGICAL_INPUT "crosshair-logical-input"
OBJECT_DECLARE_SIMPLE_TYPE(CrosshairTestDisplay, CROSSHAIR_TEST_DISPLAY)
OBJECT_DECLARE_SIMPLE_TYPE(CrosshairLogicalInput, CROSSHAIR_LOGICAL_INPUT)

#define TEST_DISPLAY_BASE 0x10000000ULL
#define TEST_INPUT_BASE 0x10001000ULL
#define TEST_WIDTH 240
#define TEST_HEIGHT 320
#define TEST_STRIDE (TEST_WIDTH * 2)
#define TEST_FB_BYTES (TEST_STRIDE * TEST_HEIGHT)
#define TEST_INPUT_CAPACITY 8

struct CrosshairTestDisplay {
    SysBusDevice parent_obj;
    MemoryRegion region;
    MemoryRegion *ram;
    QemuConsole *console;
    uint32_t framebuffer;
    uint32_t generation;
};

struct CrosshairLogicalInput {
    SysBusDevice parent_obj;
    MemoryRegion region;
    uint32_t events[TEST_INPUT_CAPACITY];
    uint32_t rejected;
    unsigned head;
    unsigned count;
};

static MemTxResult test_bad_access(const char *device, hwaddr addr,
                                   unsigned size, bool write)
{
    qemu_log_mask(LOG_GUEST_ERROR,
                  "crosshair-display-test: rejected %s %s offset=0x%"
                  HWADDR_PRIx " size=%u\n", device,
                  write ? "write" : "read", addr, size);
    return MEMTX_ERROR;
}

static bool test_framebuffer_valid(uint64_t address)
{
    return !(address & 1) && address >= E2A_RAM_BASE &&
           address <= E2A_RAM_BASE + E2A_RAM_SIZE - TEST_FB_BYTES;
}

static void test_display_refresh(void *opaque)
{
    CrosshairTestDisplay *s = opaque;
    /* Refresh/screendump observes the last committed surface, never reads
     * unpublished guest framebuffer mutations or changes the generation. */
    dpy_gfx_update_full(s->console);
}

static const GraphicHwOps test_display_ops = {
    .invalidate = test_display_refresh,
    .gfx_update = test_display_refresh,
};

static void test_display_present(CrosshairTestDisplay *s)
{
    DisplaySurface *surface = qemu_console_surface(s->console);
    uint8_t *source = memory_region_get_ram_ptr(s->ram);
    uint8_t *dest = surface_data(surface);
    unsigned x, y;
    source += s->framebuffer - E2A_RAM_BASE;
    for (y = 0; y < TEST_HEIGHT; y++) {
        uint32_t *row = (uint32_t *)(dest + y * surface_stride(surface));
        for (x = 0; x < TEST_WIDTH; x++) {
            uint16_t pixel = lduw_le_p(source + y * TEST_STRIDE + 2 * x);
            unsigned r = (pixel >> 11) & 31;
            unsigned g = (pixel >> 5) & 63;
            unsigned b = pixel & 31;
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);
            row[x] = (r << 16) | (g << 8) | b;
        }
    }
    /* Synchronous publication: the copied pixels precede generation and
     * notification. This host console surface is not a second guest buffer. */
    s->generation++;
    dpy_gfx_update_full(s->console);
}

static MemTxResult test_display_read(void *opaque, hwaddr addr, uint64_t *data,
                                    unsigned size, MemTxAttrs attrs)
{
    CrosshairTestDisplay *s = opaque;
    *data = 0;
    if (size != 4 || (addr & 3)) {
        return test_bad_access("display", addr, size, false);
    }
    switch (addr) {
    case 0x00: *data = s->framebuffer; break;
    case 0x04: *data = TEST_WIDTH; break;
    case 0x08: *data = TEST_HEIGHT; break;
    case 0x0c: *data = TEST_STRIDE; break;
    case 0x10: *data = 0x565; break;
    case 0x14: *data = s->generation; break;
    default: return test_bad_access("display", addr, size, false);
    }
    return MEMTX_OK;
}

static MemTxResult test_display_write(void *opaque, hwaddr addr, uint64_t data,
                                     unsigned size, MemTxAttrs attrs)
{
    CrosshairTestDisplay *s = opaque;
    if (size != 4 || (addr & 3)) {
        return test_bad_access("display", addr, size, true);
    }
    if (addr == 0 && test_framebuffer_valid(data)) {
        s->framebuffer = data;
        return MEMTX_OK;
    }
    if (addr == 0x14 && data == 1 && test_framebuffer_valid(s->framebuffer)) {
        test_display_present(s);
        return MEMTX_OK;
    }
    return test_bad_access("display", addr, size, true);
}

static const MemoryRegionOps test_display_mmio_ops =
    E2A_ACCESS_OPS(test_display_read, test_display_write);

static void test_display_reset_hold(Object *obj, ResetType type)
{
    CrosshairTestDisplay *s = CROSSHAIR_TEST_DISPLAY(obj);
    DisplaySurface *surface = qemu_console_surface(s->console);
    s->framebuffer = s->generation = 0;
    memset(surface_data(surface), 0, surface_stride(surface) * TEST_HEIGHT);
    dpy_gfx_update_full(s->console);
}

static void test_display_realize(DeviceState *dev, Error **errp)
{
    CrosshairTestDisplay *s = CROSSHAIR_TEST_DISPLAY(dev);
    DisplaySurface *surface;
    if (!s->ram || memory_region_size(s->ram) != E2A_RAM_SIZE) {
        error_setg(errp, "test display requires its board's 128 MiB RAM");
        return;
    }
    s->console = graphic_console_init(dev, 0, &test_display_ops, s);
    surface = qemu_create_displaysurface(TEST_WIDTH, TEST_HEIGHT);
    memset(surface_data(surface), 0, surface_stride(surface) * TEST_HEIGHT);
    dpy_gfx_replace_surface(s->console, surface);
}

static void test_display_instance_init(Object *obj)
{
    CrosshairTestDisplay *s = CROSSHAIR_TEST_DISPLAY(obj);
    memory_region_init_io(&s->region, obj, &test_display_mmio_ops, s,
                          "crosshair-display-test.display", 0x1000);
    sysbus_init_mmio(SYS_BUS_DEVICE(obj), &s->region);
}

static void test_display_class_init(ObjectClass *klass, void *data)
{
    static const VMStateDescription no_migration = {
        .name = "crosshair-test-display", .unmigratable = true,
    };
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->desc = "Crosshair synthetic RGB565 presentation test device (not ATI)";
    dc->user_creatable = false;
    dc->realize = test_display_realize;
    dc->vmsd = &no_migration;
    RESETTABLE_CLASS(klass)->phases.hold = test_display_reset_hold;
}

static bool test_event_valid(uint32_t value)
{
    unsigned tag = value >> 24;
    uint32_t text = value & 0xffffff;
    if (tag >= 1 && tag <= 7) {
        return text == 0;
    }
    return tag == 8 && text <= 0x10ffff && !(text >= 0xd800 && text <= 0xdfff);
}

static MemTxResult test_input_read(void *opaque, hwaddr addr, uint64_t *data,
                                  unsigned size, MemTxAttrs attrs)
{
    CrosshairLogicalInput *s = opaque;
    *data = 0;
    if (size != 4 || (addr & 3)) {
        return test_bad_access("input", addr, size, false);
    }
    switch (addr) {
    case 0x00: *data = s->count; break;
    case 0x04:
        if (s->count) {
            *data = s->events[s->head];
            s->events[s->head] = 0;
            s->head = (s->head + 1) % TEST_INPUT_CAPACITY;
            s->count--;
        }
        break;
    case 0x0c: *data = TEST_INPUT_CAPACITY; break;
    case 0x10: *data = s->rejected; break;
    default: return test_bad_access("input", addr, size, false);
    }
    return MEMTX_OK;
}

static MemTxResult test_input_write(void *opaque, hwaddr addr, uint64_t data,
                                   unsigned size, MemTxAttrs attrs)
{
    CrosshairLogicalInput *s = opaque;
    if (size != 4 || (addr & 3) || addr != 8) {
        return test_bad_access("input", addr, size, true);
    }
    if (!test_event_valid(data) || s->count == TEST_INPUT_CAPACITY) {
        if (s->rejected != UINT32_MAX) {
            s->rejected++;
        }
        return test_bad_access("input", addr, size, true);
    }
    s->events[(s->head + s->count) % TEST_INPUT_CAPACITY] = data;
    s->count++;
    return MEMTX_OK;
}

static const MemoryRegionOps test_input_mmio_ops =
    E2A_ACCESS_OPS(test_input_read, test_input_write);

static void test_input_reset_hold(Object *obj, ResetType type)
{
    CrosshairLogicalInput *s = CROSSHAIR_LOGICAL_INPUT(obj);
    memset(s->events, 0, sizeof(s->events));
    s->head = s->count = s->rejected = 0;
}

static void test_input_instance_init(Object *obj)
{
    CrosshairLogicalInput *s = CROSSHAIR_LOGICAL_INPUT(obj);
    memory_region_init_io(&s->region, obj, &test_input_mmio_ops, s,
                          "crosshair-display-test.input", 0x1000);
    sysbus_init_mmio(SYS_BUS_DEVICE(obj), &s->region);
}

static void test_input_class_init(ObjectClass *klass, void *data)
{
    static const VMStateDescription no_migration = {
        .name = "crosshair-logical-input", .unmigratable = true,
    };
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->desc = "Crosshair synthetic logical-event FIFO (not physical input)";
    dc->user_creatable = false;
    dc->vmsd = &no_migration;
    RESETTABLE_CLASS(klass)->phases.hold = test_input_reset_hold;
}

static void crosshair_display_test_init(MachineState *machine)
{
    DeviceState *display, *input;
    crosshair_e2b_init(machine);
    display = qdev_new(TYPE_CROSSHAIR_TEST_DISPLAY);
    object_property_add_child(OBJECT(machine), "test-display", OBJECT(display));
    CROSSHAIR_TEST_DISPLAY(display)->ram = machine->ram;
    sysbus_realize_and_unref(SYS_BUS_DEVICE(display), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(display), 0, TEST_DISPLAY_BASE);
    input = qdev_new(TYPE_CROSSHAIR_LOGICAL_INPUT);
    object_property_add_child(OBJECT(machine), "logical-input", OBJECT(input));
    sysbus_realize_and_unref(SYS_BUS_DEVICE(input), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(input), 0, TEST_INPUT_BASE);
}

static void crosshair_display_test_machine_class_init(MachineClass *mc)
{
    crosshair_e2b_machine_class_init(mc);
    mc->desc = "Crosshair display/input test (synthetic, not ATI or physical input)";
    mc->init = crosshair_display_test_init;
    mc->default_ram_id = "crosshair-display-test.ram";
}

static const TypeInfo test_device_types[] = {
    {
        .name = TYPE_CROSSHAIR_TEST_DISPLAY,
        .parent = TYPE_SYS_BUS_DEVICE,
        .instance_size = sizeof(CrosshairTestDisplay),
        .instance_init = test_display_instance_init,
        .class_init = test_display_class_init,
    }, {
        .name = TYPE_CROSSHAIR_LOGICAL_INPUT,
        .parent = TYPE_SYS_BUS_DEVICE,
        .instance_size = sizeof(CrosshairLogicalInput),
        .instance_init = test_input_instance_init,
        .class_init = test_input_class_init,
    },
};
DEFINE_TYPES(test_device_types)
DEFINE_MACHINE("crosshair-blueangel-display-test", crosshair_display_test_machine_class_init)
