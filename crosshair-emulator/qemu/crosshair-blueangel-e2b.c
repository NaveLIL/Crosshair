/*
 * SPDX-License-Identifier: GPL-2.0-only
 * Crosshair E2B: synthetic PXA26x GPIO subset, not a complete HTC board.
 * Copyright Project Crosshair contributors.
 *
 * GPIO register contract: Intel PXA26x Developer's Manual 278638-002,
 * chapter 4.1; interrupt wiring corroborated by Linux mach-pxa/irqs.h.
 * See docs/E2B_CPU_GPIO_AUDIT.md for primary sources and uncertainty labels.
 * This implementation is host-side GPL code, separate from the MIT guest.
 *
 * Compile this translation unit ONLY. Including the unchanged E2A unit
 * preserves its implementation byte-for-byte and registers both machines.
 */
#include "crosshair-blueangel-e2a.c"

#define TYPE_CROSSHAIR_E2B_GPIO "crosshair-e2b-gpio"
OBJECT_DECLARE_SIMPLE_TYPE(CrosshairE2BGPIO, CROSSHAIR_E2B_GPIO)

#define E2B_GPIO_BASE 0x40e00000ULL
#define E2B_GPIO_COUNT 90
#define E2B_GPIO_IRQ_FIRST 8

struct CrosshairE2BGPIO {
    SysBusDevice parent_obj;
    MemoryRegion region;
    qemu_irq irq[3];
    qemu_irq output[E2B_GPIO_COUNT];
    qemu_irq output_enable[E2B_GPIO_COUNT];
    uint32_t external[3];
    uint32_t latch[3];
    uint32_t direction[3];
    uint32_t rising[3];
    uint32_t falling[3];
    uint32_t status[3];
    uint32_t alternate[6];
};

static uint32_t e2b_bank_mask(unsigned bank)
{
    return bank == 2 ? 0x03ffffffU : UINT32_MAX;
}

static bool e2b_gpio_mode(CrosshairE2BGPIO *s, unsigned pin)
{
    unsigned function = (s->alternate[pin / 16] >> (2 * (pin % 16))) & 3;
    return function == (pin >= 86 ? 1 : 0);
}

static bool e2b_gpio_output(CrosshairE2BGPIO *s, unsigned pin)
{
    bool direction = (s->direction[pin / 32] >> (pin % 32)) & 1;
    return pin >= 86 ? !direction : direction;
}

static void e2b_update_outputs(CrosshairE2BGPIO *s)
{
    unsigned pin;
    for (pin = 0; pin < E2B_GPIO_COUNT; pin++) {
        bool enabled = e2b_gpio_mode(s, pin) && e2b_gpio_output(s, pin);
        bool high = (s->latch[pin / 32] >> (pin % 32)) & 1;
        /* Disconnected GPIO driver is represented by OE=0, out=0.
         * There is no dedicated peripheral driver or electrical pad model. */
        qemu_set_irq(s->output_enable[pin], enabled);
        qemu_set_irq(s->output[pin], enabled && high);
    }
}

static void e2b_update_gpio_irq(CrosshairE2BGPIO *s)
{
    qemu_set_irq(s->irq[0], (s->status[0] & 1) != 0);
    qemu_set_irq(s->irq[1], (s->status[0] & 2) != 0);
    qemu_set_irq(s->irq[2], ((s->status[0] & ~3U) |
                           s->status[1] | s->status[2]) != 0);
}

static uint32_t e2b_pin_levels(CrosshairE2BGPIO *s, unsigned bank)
{
    uint32_t levels = s->external[bank];
    unsigned pin;
    for (pin = bank * 32; pin < MIN((bank + 1) * 32, E2B_GPIO_COUNT); pin++) {
        uint32_t bit = 1U << (pin % 32);
        if (e2b_gpio_mode(s, pin) && e2b_gpio_output(s, pin)) {
            levels = (levels & ~bit) | (s->latch[bank] & bit);
        }
    }
    /* In unmodeled AF modes the external test wire supplies the sample.
     * This deterministic adapter behavior is not a dedicated pad claim. */
    return levels & e2b_bank_mask(bank);
}

static void e2b_gpio_input(void *opaque, int pin, int level)
{
    CrosshairE2BGPIO *s = opaque;
    unsigned bank = pin / 32;
    uint32_t bit = 1U << (pin % 32);
    bool previous = (s->external[bank] & bit) != 0;
    bool high = level != 0;

    s->external[bank] = (s->external[bank] & ~bit) | (high ? bit : 0);
    /* Explicit subset interpretation: only external transitions while in
     * GPIO input mode latch edges. GPDR/GAFR writes do not invent edges. */
    if (previous != high && e2b_gpio_mode(s, pin) &&
        !e2b_gpio_output(s, pin) &&
        ((high ? s->rising[bank] : s->falling[bank]) & bit)) {
        s->status[bank] |= bit;
        e2b_update_gpio_irq(s);
    }
}

static MemTxResult e2b_bad_gpio(hwaddr addr, unsigned size, bool write)
{
    qemu_log_mask(LOG_GUEST_ERROR,
                  "crosshair-e2b: rejected gpio %s offset=0x%" HWADDR_PRIx
                  " size=%u\n", write ? "write" : "read", addr, size);
    return MEMTX_ERROR;
}

static MemTxResult e2b_gpio_read(void *opaque, hwaddr addr, uint64_t *data,
                               unsigned size, MemTxAttrs attrs)
{
    CrosshairE2BGPIO *s = opaque;
    unsigned group, bank;
    *data = 0;
    if (size != 4 || (addr & 3) || addr > 0x68) {
        return e2b_bad_gpio(addr, size, false);
    }
    if (addr >= 0x54) {
        *data = s->alternate[(addr - 0x54) / 4];
        return MEMTX_OK;
    }
    group = addr / 0x0c;
    bank = (addr % 0x0c) / 4;
    switch (group) {
    case 0:
        *data = e2b_pin_levels(s, bank);
        break;
    case 1:
        *data = s->direction[bank];
        break;
    case 4:
        *data = s->rising[bank];
        break;
    case 5:
        *data = s->falling[bank];
        break;
    case 6:
        *data = s->status[bank];
        break;
    default: /* GPSR/GPCR are write-only command registers. */
        return e2b_bad_gpio(addr, size, false);
    }
    return MEMTX_OK;
}

static MemTxResult e2b_gpio_write(void *opaque, hwaddr addr, uint64_t data,
                                unsigned size, MemTxAttrs attrs)
{
    CrosshairE2BGPIO *s = opaque;
    unsigned group, bank;
    uint32_t value;
    if (size != 4 || (addr & 3) || addr > 0x68) {
        return e2b_bad_gpio(addr, size, true);
    }
    if (addr >= 0x54) {
        unsigned word = (addr - 0x54) / 4;
        s->alternate[word] = data & (word == 5 ? 0x000fffffU : UINT32_MAX);
        e2b_update_outputs(s);
        return MEMTX_OK;
    }
    group = addr / 0x0c;
    bank = (addr % 0x0c) / 4;
    value = data & e2b_bank_mask(bank);
    switch (group) {
    case 1:
        s->direction[bank] = value;
        e2b_update_outputs(s);
        break;
    case 2:
        s->latch[bank] |= value;
        e2b_update_outputs(s);
        break;
    case 3:
        s->latch[bank] &= ~value;
        e2b_update_outputs(s);
        break;
    case 4:
        s->rising[bank] = value;
        break;
    case 5:
        s->falling[bank] = value;
        break;
    case 6:
        s->status[bank] &= ~value;
        e2b_update_gpio_irq(s);
        break;
    default: /* GPLR is read-only. */
        return e2b_bad_gpio(addr, size, true);
    }
    return MEMTX_OK;
}

static const MemoryRegionOps e2b_gpio_ops =
    E2A_ACCESS_OPS(e2b_gpio_read, e2b_gpio_write);

static void e2b_gpio_reset_hold(Object *obj, ResetType type)
{
    CrosshairE2BGPIO *s = CROSSHAIR_E2B_GPIO(obj);
    /* External test-adapter wires persist across a warm system reset.
     * Latch=0 is a synthetic deterministic choice, not a pad reset fact. */
    memset(s->latch, 0, sizeof(s->latch));
    memset(s->direction, 0, sizeof(s->direction));
    memset(s->rising, 0, sizeof(s->rising));
    memset(s->falling, 0, sizeof(s->falling));
    memset(s->status, 0, sizeof(s->status));
    memset(s->alternate, 0, sizeof(s->alternate));
    e2b_update_outputs(s);
    e2b_update_gpio_irq(s);
}

static void e2b_gpio_instance_init(Object *obj)
{
    CrosshairE2BGPIO *s = CROSSHAIR_E2B_GPIO(obj);
    SysBusDevice *bus = SYS_BUS_DEVICE(obj);
    unsigned i;
    memory_region_init_io(&s->region, obj, &e2b_gpio_ops, s,
                          "crosshair-e2b.gpio", 0x1000);
    sysbus_init_mmio(bus, &s->region);
    for (i = 0; i < 3; i++) {
        sysbus_init_irq(bus, &s->irq[i]);
    }
    qdev_init_gpio_in(DEVICE(obj), e2b_gpio_input, E2B_GPIO_COUNT);
    qdev_init_gpio_out_named(DEVICE(obj), s->output, "gpio-out", E2B_GPIO_COUNT);
    qdev_init_gpio_out_named(DEVICE(obj), s->output_enable, "gpio-oe", E2B_GPIO_COUNT);
}

static void e2b_gpio_class_init(ObjectClass *klass, void *data)
{
    static const VMStateDescription no_migration = {
        .name = "crosshair-e2b-gpio", .unmigratable = true,
    };
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->desc = "Crosshair E2B synthetic PXA26x GPIO90 subset";
    dc->user_creatable = false;
    dc->vmsd = &no_migration;
    RESETTABLE_CLASS(klass)->phases.hold = e2b_gpio_reset_hold;
}

static void e2b_gpio_pic_input(void *opaque, int number, int level)
{
    CrosshairE2AState *s = opaque;
    uint32_t bit = 1U << (E2B_GPIO_IRQ_FIRST + number);
    s->pending = (s->pending & ~bit) | (level ? bit : 0);
    e2a_update_irq(s);
}

static void crosshair_e2b_init(MachineState *machine)
{
    DeviceState *gpio;
    Object *pic;
    unsigned i;
    crosshair_e2a_init(machine);
    pic = object_resolve_path_component(OBJECT(machine), "e2a");
    assert(pic != NULL);
    qdev_init_gpio_in_named(DEVICE(pic), e2b_gpio_pic_input, "gpio-irqs", 3);
    gpio = qdev_new(TYPE_CROSSHAIR_E2B_GPIO);
    object_property_add_child(OBJECT(machine), "gpio", OBJECT(gpio));
    sysbus_realize_and_unref(SYS_BUS_DEVICE(gpio), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(gpio), 0, E2B_GPIO_BASE);
    for (i = 0; i < 3; i++) {
        sysbus_connect_irq(SYS_BUS_DEVICE(gpio), i,
                           qdev_get_gpio_in_named(DEVICE(pic), "gpio-irqs", i));
    }
}

static void crosshair_e2b_machine_class_init(MachineClass *mc)
{
    static const char * const cpu_types[] = {
        ARM_CPU_TYPE_NAME("pxa260"), NULL,
    };
    crosshair_e2a_machine_class_init(mc);
    mc->desc = "Crosshair Blue Angel E2B (synthetic GPIO90, incomplete PXA26x proxy)";
    mc->init = crosshair_e2b_init;
    mc->valid_cpu_types = cpu_types;
    mc->default_ram_id = "crosshair-e2b.ram";
}

static const TypeInfo e2b_gpio_type = {
    .name = TYPE_CROSSHAIR_E2B_GPIO,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(CrosshairE2BGPIO),
    .instance_init = e2b_gpio_instance_init,
    .class_init = e2b_gpio_class_init,
};

static void e2b_register_types(void)
{
    type_register_static(&e2b_gpio_type);
}
type_init(e2b_register_types)
DEFINE_MACHINE("crosshair-blueangel-e2b", crosshair_e2b_machine_class_init)
