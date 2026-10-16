# Project Crosshair

Собственная ОС на Rust для i-mate PDA2k / HTC Blue Angel, Intel XScale PXA263 (ARMv5TE). Цель — самостоятельное ядро, аппаратная клавиатура и сенсор, приложения, звонки/SMS и надёжный сон.

**Crosshair Boot 0.1 проверен в QEMU 9.2.0 на VersatilePB/ARM926:** настоящий `no_std` Rust-код печатает `CROSSHAIR BOOT 0.1 — HELLO FROM RUST` и переходит в проверяемый цикл. Проверены normal/panic, ARM EABI5, BSS и стек. [Протокол](reports/BOOT_0.1.md).

**E2A проверен:** собственная `crosshair-blueangel-e2a` на QEMU9.2 с экспериментальным CPU260 proxy выполняет Crosshair, timer IRQ, reset/reboot и MMIO data-abort tests. [Результаты и сравнение с E1](reports/E2A_MINIMAL_BOARD.md), [контракт](docs/E2A_CONTRACT.md). Это ограниченная синтетическая плата; точность PXA263 не заявляется.

**Wave003 / E2B:** GPIO90 с особой семантикой86–89, CP15/MMU alias, маскированный pending и реальные GPIO IRQ проверены QTest/TCG на отдельной экспериментальной плате. **UI0.2:** компоненты, логические события, видимый фокус и прокручиваемый тестовый экран «Приложения» прошли19 host-тестов и20000 детерминированных операций. [Итоговый протокол и RAM](reports/WAVE_003.md), [CPU/GPIO audit](docs/E2B_CPU_GPIO_AUDIT.md), [UI0.2](docs/UI_0.2.md).

Программный RGB565 renderer240×320 с кириллицей и dirty rectangles остаётся независимым от дисплея. До Wave004 экран исполнялся на host с ARM compile-only проверкой; аппаратного LCD driver пока нет. [Основа UI0.1](docs/UI_0.1.md).

**Wave004 / First Integrated Display:** тот же `crosshair-ui` теперь исполняется внутри ARMv5TE guest на отдельной `crosshair-blueangel-display-test`. Гостевой RGB565 framebuffer и настоящая графическая консоль QEMU совпали с host PNG:23 pixel comparisons,101 событие,3 boot/reset. Backend явно synthetic/test-only, не ATI W3200. [Протокол и RAM](reports/WAVE_004.md), [дизайн-система](docs/UI_DESIGN_SYSTEM.md), [навигация](docs/UI_NAVIGATION.md), [экраны](docs/UI_SCREENS.md), [историческая спецификация W3200](docs/ATI_W3200_SPEC.md).

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
