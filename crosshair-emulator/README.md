# crosshair-emulator

Долгосрочный подпроект: воспроизводимая модель Blue Angel для разработки Crosshair без постоянного использования единственного КПК.

**Состояние 16.10.2026:** E0 feasibility и E1 PXA baseline выполнены. Собственный Rust IRQ-гость прошёл Connex/Verdex/Mainstone на QEMU9.1; независимый QTest зафиксировал register semantics и неполный reset таймера. [Отчёт E1](../reports/E1_PXA_REFERENCE.md). Собственная machine Blue Angel и GSM-модель **ещё не реализованы**. Crosshair Boot0.1/VersatilePB и PXA reference boards не являются эмуляцией PDA2k.

- [Осуществимость, источники и границы точности](FEASIBILITY.md).
- [Этапы и критерии завершения](ROADMAP.md).
- [Фактический inventory локального QEMU 9.2.0](evidence/qemu-9.2.0-inventory.json).
- [Фиксированные commit, URL и SHA-256 исследованных источников](evidence/qemu-source-manifest.json).

Здесь проверенные сведения, исполняемый reference guest, QTest и дальнейший план. Код моделей QEMU не модифицирован; используется отдельная минимальная device config. ROM, радиопрошивка, пользовательские данные и готовые сторонние бинарники в подпроект не включены.
