# crosshair-emulator

Долгосрочный подпроект: воспроизводимая модель Blue Angel для разработки Crosshair без постоянного использования единственного КПК.

**Состояние 16.10.2026:** E0 feasibility и E1 PXA baseline завершены и сохранены как исходные точки сравнения. **E2A реализован и проверен:** отдельная machine `crosshair-blueangel-e2a` на QEMU9.2 с CPU `pxa260` как экспериментальным PXA26x ISA proxy, синтетической RAM/low-vector RAM, diagnostic UART и ограниченными timer/PIC. Собственный Rust guest прошёл запуск, три CPU IRQ и повторную загрузку после system reset; четыре отрицательных гостя получили настоящие data abort. QTest отдельно проверил virtual frequency, IRQ/FIQ, W1C, rollover, reset и отмену старых deadlines. [Отчёт E2A](../reports/E2A_MINIMAL_BOARD.md), [точный контракт модели](../docs/E2A_CONTRACT.md).

**E2B реализован и проверен:** отдельная `crosshair-blueangel-e2b` добавляет GPIO90, включая AF1 и инверсию направления 86–89. TCG guest проверил CP15 reset/readback, section MMU alias, пять GPIO IRQ и повторную загрузку; отрицательные probes — три data abort и UNDEF для отсутствующих CP14 CLKCFG/PWRMODE. QTest проверил все 90 линий, AF/direction, preload, edges/W1C, PIC IRQ/FIQ, reset, строгий MMIO и output/OE. [Аудит CPU/GPIO и первоисточники](../docs/E2B_CPU_GPIO_AUDIT.md).

Это проверенный **синтетический register-level subset**, аппаратное подтверждение отсутствует. CPU остаётся `pxa260` proxy; cache maintenance — NOP, а сохранение RAM и external test inputs через warm reset — synthetic contracts. ASIC3, ATI LCD и modem ещё не реализованы. Программный [renderer/UI](../docs/UI_0.2.md) развивается отдельно; окно 240×320 не проверяет ATI MMIO. Следующая работа по LCD — исследование контракта W3200. Crosshair Boot0.1/VersatilePB и E1 reference boards сохраняют собственные границы точности.

- [Осуществимость, источники и границы точности](FEASIBILITY.md).
- [Этапы и критерии завершения; следующий контракт W3200](ROADMAP.md).
- [CPU profile: подтверждённые факты, решения и неизвестные](../docs/E2A_CPU_PROFILE.md).
- [Отчёт принятого E1](../reports/E1_PXA_REFERENCE.md).
- [Исходный inventory vanilla QEMU9.2](evidence/qemu-9.2.0-inventory.json) и [закреплённые исследовательские источники](evidence/qemu-source-manifest.json).
- [Отдельная GPL область host-модели QEMU](qemu/README.md); собственный Rust guest и test harness остаются MIT.

Воспроизведение E2A: `scripts/bootstrap-qemu-blueangel.sh`, затем `scripts/test-e2a.sh`. Воспроизведение E2B: `scripts/bootstrap-qemu-e2b.sh`, затем `scripts/test-e2b.sh`. Фактические результаты создаются в `target/artifacts/e2a-tests/`, `target/artifacts/e2a-qtest/`, `target/artifacts/e2b-tests/` и `target/artifacts/e2b-qtest/`; там сохраняются команды, SHA-256, UART, CPU records и QTest protocol. Исходные Q91 comparator и vanilla9.2 не модифицируются. ROM, радиопрошивка и пользовательские данные в подпроект не включены.
