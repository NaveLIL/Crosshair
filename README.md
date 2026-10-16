# Project Crosshair

Собственная ОС на Rust для i-mate PDA2k / HTC Blue Angel, Intel XScale PXA263 (ARMv5TE). Цель — самостоятельное ядро, аппаратная клавиатура и сенсор, приложения, звонки/SMS и надёжный сон.

**Wave007.1 / Pocket PC Desktop:** свободное рабочее пространство с серо-синими обоями240×320, компактным «Пуск», тремя небольшими ярлыками и отдельными Launcher/Today. Мышь macOS передаёт логические taps в настоящий ARM Shell; общая геометрия отвечает за hit-testing и keyboard focus. Фон восстанавливается частично, без второго framebuffer или runtime PNG/SVG. [Отчёт, PNG и память](reports/WAVE_007_1.md), [ресурсы](docs/UI_ASSET_SYSTEM.md#wave0071-static-wallpaper), [навигация](docs/SHELL_NAVIGATION.md). Команда запуска прежняя: `scripts/run-crosshair-gui.sh`.

**Wave007 / Crosshair Shell0.1:** отдельная ARM User-задача с настоящими Desktop, Today, Launcher с поиском, About, Diagnostics, Settings, меню, диалогом и переключением тем. Один RGB565 framebuffer, прежний `crosshair-ui`, kernel-controlled Present/Metrics/WaitEvent и вытесняемый Busy User. [Отчёт и кадры](reports/WAVE_007.md), [архитектура](docs/SHELL_ARCHITECTURE.md), [навигация](docs/SHELL_NAVIGATION.md).

Системные значки — закреплённый поднабор [Tabler Icons](https://github.com/tabler/tabler-icons) с сохранённой MIT-лицензией:18 SVG преобразуются при сборке в54 окрашиваемые темой маски12/16/24px,2196B read-only данных и0B дополнительного постоянного mutable state. [Каталог, происхождение и воспроизводимая генерация](docs/UI_ASSET_SYSTEM.md); SVG-движок в ОС не добавляется.

Живой сеанс на macOS: **`scripts/run-crosshair-gui.sh`**. Отдельное окно показывает актуальные пиксели консоли QEMU; клавиши Mac передаются в синтетическую FIFO, Shell исполняется в ARM TCG. Стрелки/Enter/Esc, F10 меню, Home, F1/F2 softkeys, F3 переключение, текст — поиск в Launcher. Закрытие окна или Cmd-Q завершает сеанс. Экран гостя строго240×320, окно по умолчанию увеличено2× без сглаживания. [Зависимости и команды](BUILDING.md).

**Wave006 / Preemptive Task Runtime0.1 проверен в ARM TCG:** две User-задачи с отдельными L1/L2 и одинаковыми VA→разными PA. Busy Loop без SVC вытесняется timer IRQ; другая задача продолжает реальные вычисления и SVC после fault первой. Полный `scripts/test-wave006.sh` — exit0, новые8 scenarios/16 boot-reset executions плюс прежние регрессии. Kernel extent80480B; kernel + mapped User pages + vectors105120B. [Протокол и evidence](reports/WAVE_006.md), [контексты/ABI](docs/TASK_RUNTIME.md), [аудит Wave005](docs/WAVE005_TASK_AUDIT.md). Физическая защита PXA263 не проверена.

**Wave005 / Security Foundation0.1 проверен:** отдельный User/MMU/SVC guest на неизменённой synthetic E2B прошёл24 сценария и48 boot/reset executions с healthy User recovery. Working RAM с vectors —91200B. Это узкий прототип без scheduler; UI Wave004 остаётся privileged, ARMv5 не получает NX. [Протокол](reports/WAVE_005.md), [модель безопасности](docs/SECURITY_MODEL.md), [модель угроз](docs/THREAT_MODEL.md). Crypto candidates проверены только compile-only, без ключей или включения crypto runtime.

**Crosshair Boot 0.1 проверен в QEMU 9.2.0 на VersatilePB/ARM926:** настоящий `no_std` Rust-код печатает `CROSSHAIR BOOT 0.1 — HELLO FROM RUST` и переходит в проверяемый цикл. Проверены normal/panic, ARM EABI5, BSS и стек. [Протокол](reports/BOOT_0.1.md).

**E2A проверен:** собственная `crosshair-blueangel-e2a` на QEMU9.2 с экспериментальным CPU260 proxy выполняет Crosshair, timer IRQ, reset/reboot и MMIO data-abort tests. [Результаты и сравнение с E1](reports/E2A_MINIMAL_BOARD.md), [контракт](docs/E2A_CONTRACT.md). Это ограниченная синтетическая плата; точность PXA263 не заявляется.

**Wave003 / E2B:** GPIO90 с особой семантикой86–89, CP15/MMU alias, маскированный pending и реальные GPIO IRQ проверены QTest/TCG на отдельной экспериментальной плате. **UI0.2:** компоненты, логические события, видимый фокус и прокручиваемый тестовый экран «Приложения» прошли19 host-тестов и20000 детерминированных операций. [Итоговый протокол и RAM](reports/WAVE_003.md), [CPU/GPIO audit](docs/E2B_CPU_GPIO_AUDIT.md), [UI0.2](docs/UI_0.2.md).

Программный RGB565 renderer240×320 с кириллицей и dirty rectangles остаётся независимым от дисплея. До Wave004 экран исполнялся на host с ARM compile-only проверкой; аппаратного LCD driver пока нет. [Основа UI0.1](docs/UI_0.1.md).

**Wave004 / First Integrated Display:** тот же `crosshair-ui` теперь исполняется внутри ARMv5TE guest на отдельной `crosshair-blueangel-display-test`. Гостевой RGB565 framebuffer и настоящая графическая консоль QEMU совпали с host PNG:23 pixel comparisons,101 событие,3 boot/reset. Backend явно synthetic/test-only, не ATI W3200. [Протокол и RAM](reports/WAVE_004.md), [дизайн-система](docs/UI_DESIGN_SYSTEM.md), [навигация](docs/UI_NAVIGATION.md), [экраны](docs/UI_SCREENS.md), [историческая спецификация W3200](docs/ATI_W3200_SPEC.md).

Для **Crosshair Shell0.1** владелец утвердил [визуальный reference](docs/UI_DESIGN_SYSTEM.md#approved-visual-reference-for-crosshair-shell-01): отдельные Desktop/app grid и Today, компактная серо-синяя система на существующем движке240×320/RGB565/Cozette. Wave007 реализует функциональные экраны по этому направлению; физические LCD/input и телефонные службы остаются отдельными этапами.

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

Полный текстовый пакет публичного дерева: `scripts/pack-repomix.sh`, [состав, проверки и manifest](docs/REPOSITORY_PACK.md). Приватная родительская история, caches и OEM binaries в него не входят.

Собственный код распространяется по [MIT](LICENSE). Сторонние материалы сохраняют свои условия: [RIGHTS_AND_PUBLICATION.md](RIGHTS_AND_PUBLICATION.md). В репозиторий не входят ROM, фотографии, пользовательские данные и toolchain binaries. Текстовые журналы с нормализованными путями — presentation copies; guest bytes и их хеши не подменяются. [Манифест публичного экспорта](reports/public-export-audit.json).
