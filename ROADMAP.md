# Дорожная карта

| Этап | Критерий результата | Текущий статус |
|---|---|---|
| Boot 0.1 / QEMU | Реальное ARMv5 выполнение Rust, UART, normal/panic и контролируемый idle | Проверено на VersatilePB/ARM926; [протокол](reports/BOOT_0.1.md) |
| E2A / собственная virtual board | Реальное исполнение Crosshair, timer/IRQ, reset и invalid-MMIO tests | Проверено на экспериментальном CPU260 subset; [протокол](reports/E2A_MINIMAL_BOARD.md) |
| UI0.1 / software primitives | RGB565240×320, кириллица, bounded dirty regions, host pixel tests | Независимый software layer; [контракт](docs/UI_0.1.md), не аппаратный LCD |
| M1 / ROM и QWERTY | Проверяемый PE QwertyKey.dll, хеши, imports/exports и воспроизводимый decoder | Синтетические parser tests проверены; исходный ROM для полного повторения отсутствует |
| Blue Angel / аппаратный boot | Доказанные HaRET/RAM/CPU/diagnostic contracts, затем отдельно разрешённое испытание | Собираемый RAM-only adapter; физически не проверен |
| Ввод/экран | Собственный ATI LCD, TSC2200 и ASIC3 QWERTY drivers | Исследование |
| Карманная среда | Память, события/задачи, SD files и приложения | Дальнейший этап |
| Телефон | Звонки/SMS, разговорный звук и wake | Протокол модема неизвестен; functional test model планируется отдельно |
| Надёжность | Сон/пробуждение, сохранность данных и измеренная автономность | Дальнейший этап |

PXA reference: [контракт](docs/PXA_REFERENCE_CONTRACT.md), [результаты](reports/E1_PXA_REFERENCE.md). Это исторические reference boards, не Blue Angel.

[crosshair-emulator имеет отдельные этапы и критерии точности](crosshair-emulator/ROADMAP.md). Functional mock не закрывает register-level драйвер и не подтверждает аппаратную работу.
