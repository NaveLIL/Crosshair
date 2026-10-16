# Инженерные решения

- Самостоятельная ОС; Linux/Windows CE — исследовательские источники, без зависимости от их runtime.
- Основной язык Rust `no_std`, минимальный ARM Assembly; маленькое монолитное ядро и отдельные BSP.
- ARMv5TE target, core source build, pinned toolchains; ограничения атомиков проверяются фактическим target cfg.
- Аппаратная QWERTY и сенсор равноправны; русская раскладка отделяется от scan codes и UI language.
- Звонки/SMS, разговорный звук, сон и wake входят в конечную цель.
- Первые эксперименты не требуют записи Flash. RAM handoff также меняет состояние и требует резервирования данных.
- VersatilePB execution, historical PXA reference и Blue Angel hardware validation — отдельные результаты.
- Own code: MIT в [LICENSE](LICENSE). Условия сторонних исходников и данных не заменяются лицензией проекта.

[Архитектура](ARCHITECTURE.md), [неизвестные параметры](OPEN_QUESTIONS.md), [загрузочный контракт](BOOT.md).

- E2A использует честно обозначенный CPU260 ISA proxy, собственную композицию и ограниченный register-level subset; PXA263 MIDR не подделывается. QEMU9.1 остаётся comparator. [Основание](docs/E2A_CPU_PROFILE.md).
- GPL host emulator C отделён в `crosshair-emulator/qemu/`; Rust guest и программный UI остаются MIT, GPL runtime в ядро не переносится.
