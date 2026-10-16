# Engineering wave 002: E2A + UI0.1

**Реализовано и проверено 16.10.2026.** Принятый Boot0.1/E1 baseline сохранён. Собственный Crosshair исполняется на собственной минимальной QEMU board; независимый программный renderer работает в host tests и компилируется под ARMv5TE.

| Результат | Фактическая проверка |
|---|---|
| E2A `crosshair-blueangel-e2a` | Две загрузки в одном process через system_reset; UART,3 timer IRQ/boot, ARM exception return, стеки, BSS poison/readback и idle |
| Ошибки MMIO |4 TCG data-abort probes с DFSR/EA/DFAR и abort vector |
| E2A device subset | QTest exact3.6864MHz, IRQ/FIQ outputs, mask/routing/W1C, rollover, полный timer/PIC reset и отмена старых deadlines |
| Boot0.1 | Normal/panic execution и compile-only HaRET adapter |
| E1 | Connex/Verdex/Mainstone:3 guest PASS +3 QTest PASS_WITH_RECORDED_MODEL_LIMITATIONS; прежний reset limitation воспроизведён |
| Исследовательский parser |19 существующих tests PASS |
| UI0.1 |11 host tests, pixel golden, PNG240×320; отдельная ARMv5TE no_std library compile verification, не ARM execution renderer |
| Шрифт |163 glyphs ASCII/русский/Ёё/тире/replacement,2119 bitmap bytes; MIT attribution, pinned BDF и generator --check PASS |

Один общий вызов `scripts/test-next-wave.sh` реально завершился с кодом0. [Полный журнал](NEXT_WAVE_TESTS.log), [UI validation](ui/validation.json), [E2A evidence](../crosshair-emulator/evidence/e2a/manifest.json). Host paths в опубликованных текстовых копиях нормализованы; hashes исходных guest outputs сохранены.

[E2A report и сравнение с E1](E2A_MINIMAL_BOARD.md) содержит подтверждённые и неизвестные параметры, hashes и объяснение model contract. [UI architecture](../docs/UI_0.1.md) описывает clipping, память, transactional dirty present, шрифт и future input/display boundary. Макс. software framebuffer span153600bytes, без второго full framebuffer;8 dirty rectangles. Меньшие strips поддерживаются в локальных координатах. Библиотека не использует unsafe, heap, MMIO или host OS.

**Следующие конкретные задачи:**

1. E2B: уточнить CP14/15/MMU/cache/reset и PXA26x90GPIO contract, не подделывая PXA263 MIDR. Реальные RAM banks/aliases остаются неизвестны.
2. Дисплей: закрепить ATI W3200 aperture/register widths, pixel byte order, stride, panel variant и reset/IRQ contract. Затем отдельная register-level model и target present adapter; встроенный PXA LCD не заменяет ATI.
3. Renderer: strips/tile origin для частичного repaint, проверка реального transport completion/error, затем видимый focus и общий logical input path для stylus/QWERTY. Калибровка и controller scan codes отделены от UI actions; desktop пока не реализуется.
4. M1 QwertyKey.dll остаётся отдельным приоритетом. Нужен проверяемый исходный ROM input и decoder; E2A и UI не закрывают эту задачу.

Аппаратное подтверждение отсутствует. E2A CPU260 proxy, synthetic RAM/vector loader и test UART не являются точным PXA263/HTC; clocks/power/Flash/ASIC3/LCD/GSM/SDIO/Wi-Fi/audio настоящего устройства не проверялись. Никаких операций с физическим PDA, Flash/Radio/CID/SD не выполнялось. GPL QEMU host code находится отдельно от MIT Rust guest/UI.
