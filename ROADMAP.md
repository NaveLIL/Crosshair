# Дорожная карта

| Этап | Критерий результата | Текущий статус |
|---|---|---|
| Boot 0.1 / QEMU | Реальное ARMv5 выполнение Rust, UART, normal/panic и контролируемый idle | Проверено на VersatilePB/ARM926; [протокол](reports/BOOT_0.1.md) |
| E2A / собственная virtual board | Реальное исполнение Crosshair, timer/IRQ, reset и invalid-MMIO tests | Проверено на экспериментальном CPU260 subset; [протокол](reports/E2A_MINIMAL_BOARD.md) |
| UI0.1 / software primitives | RGB565240×320, кириллица, bounded dirty regions, host pixel tests | Независимый software layer; [контракт](docs/UI_0.1.md), не аппаратный LCD |
| E2B / GPIO и CPU audit | GPIO90, CP15/MMU, direction/AF/edge/IRQ/reset/error coverage | Проверено QTest и TCG; [Wave003](reports/WAVE_003.md), CPU260 proxy, без hardware accuracy claim |
| UI0.2 / интерактивный слой | Компоненты, фокус, события, выбор/прокрутка без heap | 19 host-тестов, 20000 stress-операций, ARM compile-only; [контракт](docs/UI_0.2.md) |
| Wave004 / integrated display | Та же UI library исполняется в ARM guest, observable240×320 RGB565 и test input | 3boot/101events/23exact pixel comparisons; [протокол](reports/WAVE_004.md), synthetic test-only, не ATI |
| UI Design System0.1 | Центральные RGB565/geometry, навигация и контракты будущих приложений | [Дизайн](docs/UI_DESIGN_SYSTEM.md), [навигация](docs/UI_NAVIGATION.md), [экраны](docs/UI_SCREENS.md); один законченный AppsScreen |
| Wave005 / Security Foundation0.1 | User/MMU/SVC permissions, bounded copy-in, fault termination и healthy recovery | 24cases/48boots на неизменённом E2B; working RAM91200B с vectors. [Протокол](reports/WAVE_005.md), [security model](docs/SECURITY_MODEL.md), [threat model](docs/THREAT_MODEL.md). Без scheduler/modern XN; crypto compile-only |
| Wave006 / Preemptive Task Runtime0.1 | Две изолированные User-задачи, timer preemption без SVC, fault containment и полный context return | 8cases/16boots ARM TCG + прежние регрессии; [протокол](reports/WAVE_006.md), [ABI](docs/TASK_RUNTIME.md). Kernel80480B; mapped working RAM105120B; static lifetime, hardware не проверен |
| Wave007 / Crosshair Shell0.1 | User Mode Desktop/app grid, Today, реальные системные экраны, bounded input/wait, видимый интерактивный Mac сеанс | Реализован отдельный User Shell на прежнем renderer; [протокол](reports/WAVE_007.md), [архитектура](docs/SHELL_ARCHITECTURE.md), [навигация](docs/SHELL_NAVIGATION.md). UI/input backend synthetic, физический LCD/TSC2200 не реализованы |
| Wave007.1 / Pocket PC Desktop | Обои, свободная рабочая область, компактные ярлыки, отдельные Launcher/Today, экспериментальные taps и частичная композиция | [Протокол, кадры и память](reports/WAVE_007_1.md); прежние kernel/scheduler/MMU/UI renderer и QEMU model сохранены. Мышь — host adapter, физический sensor driver отсутствует |
| Wave007.2 / Hardware-first UX | Standard/Compact/Immersive на одном Surface, плотные системные экраны, временная панель, pointer capture и семантические клавиши | [Протокол и память](reports/WAVE_007_2.md), [политика Shell](docs/ADAPTIVE_SHELL.md), [аппаратные источники и будущие приложения](docs/HARDWARE_FIRST_UX.md). Без новых приложений, Clipboard Broker или физических input drivers |
| M1 / ROM и QWERTY | Проверяемый PE QwertyKey.dll, хеши, imports/exports и воспроизводимый decoder | Синтетические parser tests проверены; исходный ROM для полного повторения отсутствует |
| Blue Angel / аппаратный boot | Доказанные HaRET/RAM/CPU/diagnostic contracts, затем отдельно разрешённое испытание | Собираемый RAM-only adapter; физически не проверен |
| Ввод/экран | Собственный ATI LCD, TSC2200 и ASIC3 QWERTY drivers | Исследование |
| Задняя VGA-камера | Идентифицированные sensor/interface/power contracts, затем отдельный capture backend с проверенными границами буферов | Паспортный color CMOS/VGA 640×480 подтверждён [руководством, с.9/129/162](HARDWARE.md); sensor, interface, регистры, clocks/reset/IRQ/DMA и power sequence неизвестны. Исследование OEM camera-компонентов и исторических исходников; драйвер не реализован |
| Карманная среда | Память, события/задачи, SD files и приложения | Дальнейший этап |
| Телефон | Звонки/SMS, разговорный звук и wake | Протокол модема неизвестен; functional test model планируется отдельно |
| Надёжность | Сон/пробуждение, сохранность данных и измеренная автономность | Дальнейший этап |

PXA reference: [контракт](docs/PXA_REFERENCE_CONTRACT.md), [результаты](reports/E1_PXA_REFERENCE.md). Это исторические reference boards, не Blue Angel.

[crosshair-emulator имеет отдельные этапы и критерии точности](crosshair-emulator/ROADMAP.md). Functional mock не закрывает register-level драйвер и не подтверждает аппаратную работу.

После проверенных static task lifetime/preemption и User Shell следующий security рубеж — loader ownership/authority, general checked copy и teardown до memory reuse с сохранением User/SVC/task/Shell regressions; действующих filesystem permissions, CSPRNG/key storage и signed loader пока нет. Следующий UI шаг — выделение одного builtin-экрана в самостоятельное User-приложение через ограниченный application/display contract. Для физического дисплея [исторический W3200 contract](docs/ATI_W3200_SPEC.md) уже исследован: нужны metadata WM/HaRET framebuffer и отдельный ATI backend boundary. Физический ввод требует отдельно подтверждённых ASIC3/QWERTY и TSC2200 контрактов; логические события UI тестируются отдельно, интерактивный Mac adapter не является драйвером PDA2k. M1/QwertyKey.dll сохраняет приоритет при наличии исходного ROM для воспроизводимого анализа. CP14 clock/power, реальные cache/errata, sleep/wake и pin electronics остаются открытыми; новые устройства без контрактов не добавляются.
