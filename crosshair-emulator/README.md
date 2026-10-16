# crosshair-emulator

Долгосрочный подпроект: воспроизводимая модель Blue Angel для разработки Crosshair без постоянного использования единственного КПК.

**Состояние 16.10.2026:** E0 feasibility и E1 PXA baseline завершены и сохранены как исходные точки сравнения. **E2A реализован и проверен:** отдельная machine `crosshair-blueangel-e2a` на QEMU9.2 с CPU `pxa260` как экспериментальным PXA26x ISA proxy, синтетической RAM/low-vector RAM, diagnostic UART и ограниченными timer/PIC. Собственный Rust guest прошёл запуск, три CPU IRQ и повторную загрузку после system reset; четыре отрицательных гостя получили настоящие data abort. QTest отдельно проверил virtual frequency, IRQ/FIQ, W1C, rollover, reset и отмену старых deadlines. [Отчёт E2A](../reports/E2A_MINIMAL_BOARD.md), [точный контракт модели](../docs/E2A_CONTRACT.md).

**E2B реализован и проверен:** отдельная `crosshair-blueangel-e2b` добавляет GPIO90, включая AF1 и инверсию направления 86–89. TCG guest проверил CP15 reset/readback, section MMU alias, пять GPIO IRQ и повторную загрузку; отрицательные probes — три data abort и UNDEF для отсутствующих CP14 CLKCFG/PWRMODE. QTest проверил все 90 линий, AF/direction, preload, edges/W1C, PIC IRQ/FIQ, reset, строгий MMIO и output/OE. [Аудит CPU/GPIO и первоисточники](../docs/E2B_CPU_GPIO_AUDIT.md).

**Wave004 реализован и проверен:** отдельная `crosshair-blueangel-display-test` исполняет Rust UI в TCG через собственные synthetic RGB565 display и logical-input FIFO. Три загрузки обработали 101 событие; 23 сравнения ARM/host/QEMU дали совпадение всех пикселей, framebuffer/stack guards и sentinel сохранены. QTest отдельно проверил все 65536 RGB565 значений, публикацию кадра, bounds, FIFO/Unicode/rejection и reset. Это **test-only протокол, не ATI, физическая клавиатура или touch**; [отчёт Wave004](../reports/WAVE_004.md).

Это проверенный **синтетический register-level subset**, аппаратное подтверждение отсутствует. CPU остаётся `pxa260` proxy; cache maintenance — NOP, а сохранение RAM и external test inputs через warm reset — synthetic contracts. ASIC3, ATI LCD и modem ещё не реализованы. [Исследование W3200](../docs/ATI_W3200_SPEC.md) установило исторические адреса, mapping памяти, RGB565/pitch и panel data; реальный cold-init и WM/HaRET handoff остаются неизвестными. Программный renderer и synthetic display не закрывают эти пробелы. Crosshair Boot0.1/VersatilePB и E1 reference boards сохраняют собственные границы точности.

- [Осуществимость, источники и границы точности](FEASIBILITY.md).
- [Этапы и критерии завершения; следующий ATI backend boundary](ROADMAP.md).
- [CPU profile: подтверждённые факты, решения и неизвестные](../docs/E2A_CPU_PROFILE.md).
- [Отчёт принятого E1](../reports/E1_PXA_REFERENCE.md).
- [Исходный inventory vanilla QEMU9.2](evidence/qemu-9.2.0-inventory.json) и [закреплённые исследовательские источники](evidence/qemu-source-manifest.json).
- [Отдельная GPL область host-модели QEMU](qemu/README.md); собственный Rust guest и test harness остаются MIT.

Воспроизведение E2A: `scripts/bootstrap-qemu-blueangel.sh`, затем `scripts/test-e2a.sh`. Воспроизведение E2B: `scripts/bootstrap-qemu-e2b.sh`, затем `scripts/test-e2b.sh`. Фактические результаты создаются в `target/artifacts/e2a-tests/`, `target/artifacts/e2a-qtest/`, `target/artifacts/e2b-tests/` и `target/artifacts/e2b-qtest/`; там сохраняются команды, SHA-256, UART, CPU records и QTest protocol. Исходные Q91 comparator и vanilla9.2 не модифицируются. ROM, радиопрошивка и пользовательские данные в подпроект не включены.

Воспроизведение Wave004: `scripts/bootstrap-qemu-display-test.sh`, затем `scripts/test-display.sh`. Результаты — `target/artifacts/display-test/execution/` и `target/artifacts/display-qtest/`; режим запуска и границы проверки описаны в [отчёте](../reports/WAVE_004.md).
