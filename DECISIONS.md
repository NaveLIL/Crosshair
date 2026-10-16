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
