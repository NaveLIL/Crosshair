# Открытые технические вопросы

- Чем PXA263/26x отличается от доступных PXA255/260/261/262/270 QEMU CPU/SoC моделей: GPIO, CP14/15, reset и MMU/cache quirks?
- Какие физические RAM banks/aliases и HaRET reservations допустимы для целевого устройства?
- Полностью ли выбранный HaRET binary соответствует изученному source path; что остаётся активным в DMA/периферии?
- Как наблюдать физическую загрузку без предположения о пригодности FFUART, связанного с модемом?
- Какой codec/framing использует QwertyKey.dll; где проходит граница QwertyKey/keybddr?
- Какие ATI panel variant, framebuffer/stride, TSC2200 и ASIC3 keyboard register contracts подтверждены?
- Как устроены ASIC3/TMIO SD, power retention и wake routing?
- Каковы DPRAM modem framing/handshake, call/SMS/audio и modem wake contracts?

[План исследований](docs/RESEARCH_NEXT.md), [HaRET](docs/BLUEANGEL_BOOT_RESEARCH.md), [эмулятор](crosshair-emulator/FEASIBILITY.md). Неизвестные параметры не заполняются аналогиями с другой платой.
