# Project Crosshair

Собственная ОС на Rust для i-mate PDA2k / HTC Blue Angel, Intel XScale PXA263 (ARMv5TE). Цель — самостоятельное ядро, аппаратная клавиатура и сенсор, приложения, звонки/SMS и надёжный сон.

**Crosshair Boot 0.1 проверен в QEMU 9.2.0 на VersatilePB/ARM926:** настоящий `no_std` Rust-код печатает `CROSSHAIR BOOT 0.1 — HELLO FROM RUST` и переходит в проверяемый цикл. Проверены normal/panic, ARM EABI5, BSS и стек. [Протокол](reports/BOOT_0.1.md).

Blue Angel имеет отдельный собираемый HaRET flat-image адаптер; физического запуска и готовых аппаратных драйверов пока нет. QEMU VersatilePB не эмулирует Blue Angel.

```sh
scripts/bootstrap-rust.sh
scripts/bootstrap-qemu.sh
scripts/test.sh
scripts/run-qemu.sh
```

Основная среда для Windows 11 — WSL2/Linux. Подтверждённая текущая сборка выполнена на macOS x86_64; установка WSL здесь не заявляется проверенной. [BUILDING.md](BUILDING.md) содержит версии, зависимости и команды; [BOOT.md](BOOT.md) — загрузочный контракт и диагностику.

Отдельный [crosshair-emulator](crosshair-emulator/README.md) исследует точную модель Blue Angel. Исторические Connex/Verdex/Mainstone удалены из QEMU9.2; похожий CPU не заменяет плату. PXA reference: [контракт](docs/PXA_REFERENCE_CONTRACT.md), [результаты](reports/E1_PXA_REFERENCE.md). Это исторические reference boards, не Blue Angel.

Технические документы: [аппаратура](HARDWARE.md), [архитектура](ARCHITECTURE.md), [дорожная карта](ROADMAP.md), [неизвестные параметры](OPEN_QUESTIONS.md), [M1 ROM/клавиатура](REVERSE_ENGINEERING.md), [источники](SOURCES.md).

Собственный код распространяется по [MIT](LICENSE). Сторонние материалы сохраняют свои условия: [RIGHTS_AND_PUBLICATION.md](RIGHTS_AND_PUBLICATION.md). В репозиторий не входят ROM, фотографии, пользовательские данные и toolchain binaries. Текстовые журналы с нормализованными путями — presentation copies; guest bytes и их хеши не подменяются. [Манифест публичного экспорта](reports/public-export-audit.json).
