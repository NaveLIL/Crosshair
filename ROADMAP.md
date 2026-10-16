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
| M1 / ROM и QWERTY | Проверяемый PE QwertyKey.dll, хеши, imports/exports и воспроизводимый decoder | Синтетические parser tests проверены; исходный ROM для полного повторения отсутствует |
| Blue Angel / аппаратный boot | Доказанные HaRET/RAM/CPU/diagnostic contracts, затем отдельно разрешённое испытание | Собираемый RAM-only adapter; физически не проверен |
| Ввод/экран | Собственный ATI LCD, TSC2200 и ASIC3 QWERTY drivers | Исследование |
| Карманная среда | Память, события/задачи, SD files и приложения | Дальнейший этап |
| Телефон | Звонки/SMS, разговорный звук и wake | Протокол модема неизвестен; functional test model планируется отдельно |
| Надёжность | Сон/пробуждение, сохранность данных и измеренная автономность | Дальнейший этап |

PXA reference: [контракт](docs/PXA_REFERENCE_CONTRACT.md), [результаты](reports/E1_PXA_REFERENCE.md). Это исторические reference boards, не Blue Angel.

[crosshair-emulator имеет отдельные этапы и критерии точности](crosshair-emulator/ROADMAP.md). Functional mock не закрывает register-level драйвер и не подтверждает аппаратную работу.

Следующий небольшой рубеж: установить W3200 framebuffer/stride/format/transfer contract по первоисточникам, затем подключить bounded display backend через существующий dirty-present callback. Физический ввод требует отдельно подтверждённых ASIC3/QWERTY и TSC2200 контрактов; логические события UI уже тестируются независимо. M1/QwertyKey.dll сохраняет приоритет при наличии исходного ROM для воспроизводимого анализа. CP14 clock/power, реальные cache/errata, sleep/wake и pin electronics остаются открытыми; новые устройства без контрактов не добавляются.
