# Осуществимость собственного эмулятора Blue Angel

Срез: **16.10.2026**. Результат: полезная модель строится по частям; **E2A и E2B реализованы и проверены** как отдельные `crosshair-blueangel-e2a` / `crosshair-blueangel-e2b` на отдельной QEMU9.2. Готовой полной модели Blue Angel в исходном QEMU нет. Большую часть специфической периферии предстоит описать и реализовать. Полная точность устройства, работа WM ROM и аппаратно подтверждённые звонки не установлены.

**Дополнение после E1:** QEMU9.1 теперь собран отдельно; собственный ARM IRQ guest и независимый QTest реально прошли на Connex/Verdex/Mainstone. Сохранены известные ограничения reset/OIER/UART. [Отчёт E1](../reports/E1_PXA_REFERENCE.md). Сравнение исходников ниже сохраняется как feasibility E0; Q91 остаётся неизменяемым comparator.

**Дополнение после E2A:** собственная board composition использует `pxa260` как явно ограниченный ISA proxy, синтетическую RAM/low vectors, diagnostic UART, четыре timer и PIC subset. Фактические TCG результаты подтверждают UART, три CPU IRQ, system-reset reboot и четыре настоящих data abort; QTest подтверждает3 686 400 ticks/sec, IRQ/FIQ transitions, W1C, rollover и reset/callback cancellation. [Контракт](../docs/E2A_CONTRACT.md), [отчёт](../reports/E2A_MINIMAL_BOARD.md). Это **реализовано и проверено в эмуляторе**, без GPIO, точного PXA263, экрана или GSM.

**Дополнение после E2B:** GPIO90, включая AF1/inverted direction 86–89, реализован отдельной machine. TCG подтвердил CP15 reset/readback, functional section MMU alias, пять GPIO IRQ и reset reboot; отрицательные probes — три MMIO data abort и два UNDEF для отсутствующих CLKCFG/PWRMODE CP14. QTest проверил все 90 линий, AF/direction/preload/edges/W1C, PIC IRQ/FIQ, outputs/OE и reset/error paths. [Аудит с закреплёнными источниками](../docs/E2B_CPU_GPIO_AUDIT.md). CPU остаётся `pxa260` proxy, cache maintenance NOP; warm RAM/external-input retention — synthetic policy. Полнота PXA263 и аппаратная точность не заявлены.

## Исходный inventory E0 и текущие E2A/E2B

Выполнены `local/qemu/bin/qemu-system-arm --version`, `-machine help`, `-cpu help`. [Исходный вывод и его SHA-256](evidence/qemu-9.2.0-inventory.json) сохранены для исходной vanilla9.2 без запуска гостя. Добавленные E2A/E2B собираются отдельно:

| Наблюдение | Результат / статус |
|---|---|
| Локальная версия | QEMU **9.2.0**, выполнено и проверено |
| `versatilepb`, `arm926` | Присутствуют; используются основным Boot 0.1 |
| Machines `connex`, `verdex`, `mainstone`, `blueangel` | Отсутствуют в фактическом списке |
| CPU `pxa255`, `pxa260`, `pxa261`, `pxa262`, варианты `pxa270` | Присутствуют в списке CPU; наличие имени не создаёт SoC или плату |
| CPU `pxa263` | Отсутствует; точная модель PXA263 не найдена |
| Собственные экспериментальные E2A/E2B | **Реализованы и проверены** в отдельных модифицированных9.2; отсутствуют в исходном vanilla inventory |

Удаление машин PXA2xx в **9.2** подтверждено `Q92:docs/about/removed-features.rst` и [официальной историей удалений](https://www.qemu.org/docs/master/about/removed-features.html). Локальная 9.2 содержит остаточные CPU-типы, но их список сам по себе не является поддержкой плат PXA. Версию 9.2 нельзя использовать для команд `-M connex` из старых инструкций.

## Неизменяемые первоисточники

Обозначения ниже всегда включают конкретный commit. Полные URL, размеры и SHA-256 **34 файлов QEMU и 9 файлов PXADroid**: [source manifest](evidence/qemu-source-manifest.json). Для E0 QEMU и Linux читались как исследовательские источники. В E2A host timer/PIC implementation производна от Q91; происхождение и GPL-2.0-only закреплены в [отдельной области](qemu/README.md). Код Linux в Rust guest не переносился.

| Метка | Репозиторий / версия / commit | Прочитанные ключевые пути |
|---|---|---|
| **Q91** | [QEMU v9.1.0](https://github.com/qemu/qemu/tree/fd1952d814da738ed107e05583b3e02ac11e88ff), `fd1952d814da738ed107e05583b3e02ac11e88ff` | `hw/arm/gumstix.c`, `mainstone.c`, `pxa2xx.c`, `pxa2xx_pic.c`, `pxa2xx_gpio.c`; `hw/timer/pxa2xx_timer.c`; `hw/dma/pxa2xx_dma.c`; `hw/sd/pxa2xx_mmci.c`; `target/arm/tcg/cpu32.c`; `docs/system/arm/gumstix.rst`, `mainstone.rst` |
| **Q82** | [QEMU v8.2.0](https://github.com/qemu/qemu/tree/1600b9f46b1bd08b00fe86c46ef6dbb48cbe10d6), `1600b9f46b1bd08b00fe86c46ef6dbb48cbe10d6` | `hw/arm/gumstix.c`, `mainstone.c`, `pxa2xx.c`, `Kconfig`, `meson.build`; обе board docs |
| **Q92** | [QEMU v9.2.0](https://github.com/qemu/qemu/tree/ae35f033b874c627d81d51070187fbf55f0bf1a7), `ae35f033b874c627d81d51070187fbf55f0bf1a7` | `docs/about/removed-features.rst`, `target/arm/tcg/cpu32.c`, `hw/arm/Kconfig` |
| **BA** | [PXADroid pxakernel](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/), `3712fd6f197113f19959eba85b3628b202e30d64` | `arch/arm/mach-pxa/blueangel.c`, `include/mach/blueangel.h`, `htc_calypso.c`; `drivers/mfd/asic3.c`; TSC2X0X, HTC ASIC keyboard, W100 framebuffer и Blue Angel audio |

Точная ревизия источника не доказывает точность эмуляции. Старые версии QEMU здесь — базовые точки исследования, а не утверждение об актуальной поддержке их веток. Q91 затем собран и исполнен в E1; Q82 остался статическим сравнением, Q92 стал отдельной базой E2A/E2B. Из Linux не переносились GPL-драйверы; при будущем reuse сохранять исходные copyright/license и фиксировать границу собственного кода. Собственный Rust guest и test harness Crosshair распространяются по MIT; производный host QEMU C — по GPL-2.0-only; условия сторонних исходников сохраняются.

## Что дают Connex, Verdex и Mainstone II

Исходники и [официальная документация Gumstix](https://qemu.readthedocs.io/en/v9.1.3/system/arm/gumstix.html), [Mainstone II](https://qemu.readthedocs.io/en/v9.1.3/system/arm/mainstone.html) подтверждают исторические модели. Их регистрация проверена по `Q91/Q82:hw/arm/Kconfig`, `meson.build` и machine classes.

| Историческая machine | CPU и память, заданные исходником Q91 | Полезно для Crosshair | Не соответствует Blue Angel |
|---|---|---|---|
| `connex` | `pxa255_init`, RAM 64 MiB, NOR 16 MiB; `hw/arm/gumstix.c:45–71` | Наиболее близкая из трёх отправная точка по поколению SoC; PXA25x PIC/timer/DMA/GPIO/SSP/MMCI и UART wiring | PXA255 не PXA263; фиксированный RAM size не превращается в 128 MiB простым `-m`; другая Flash/плата/NIC/периферия |
| `verdex` | PXA270, default `pxa270-c0`; RAM 256 MiB, NOR 32 MiB; `gumstix.c:48–49,74–92,110–117` | Пример composition и более нового семейства PXA | PXA27x, другая память, GPIO/IRQ и устройства |
| `mainstone` | PXA270, default `pxa270-c5`; RAM 64 MiB, ROM region 8 MiB, два NOR по 32 MiB; `hw/arm/mainstone.c:96–159` | Наглядные kernel-load, IRQ FPGA, SD и keypad connections | Mainstone FPGA и PXA27x matrix keypad не ASIC3 Blue Angel; адреса платы и LCD не совпадают |

Q82 содержит те же три machine и эти базовые размеры. В Q91 они уже помечены устаревшими и необслуживаемыми. В `Q91:hw/arm/pxa2xx.c:2237–2270` PXA255 CPU жёстко выбран, GPIO задано **85**; историческая Blue Angel конфигурация использует GPIO89 codec reset (`BA:arch/arm/mach-pxa/include/mach/blueangel.h`). Это конкретный сигнал, что нужна проверка PXA26x, а не переименование Connex. `Q91:target/arm/tcg/cpu32.c:805–863,1029–1041` определяет PXA250/255/260/261/262/270, но не PXA263.

Выбор исполнен: E1 использует изолированную Q91, E2A — собственную минимальную composition на отдельной Q92 с переносом ограниченного timer/PIC подхода и собственным reset. Monolithic PXA255 SoC не переименован в PXA263. E2B добавил GPIO90 и проверенные functional CP15/MMU probes; [установленные источниками свойства и remaining unknowns](../docs/E2B_CPU_GPIO_AUDIT.md) разделены. Следующий display шаг — исследование контракта W3200; ATI-модели ещё нет. Основной VersatilePB Boot0.1 и E1 сохраняются как принятые регрессионные точки.

## Уровни точности

1. **Functional mock:** выдаёт события через явно тестовый интерфейс Crosshair. Полезен для приложения/телефонной машины состояний; не проверяет MMIO, электрические сигналы или протокол реального устройства.
2. **Register-level model:** отображает доказанные регистры, ширины, reset values, side effects, IRQ/DMA/clock behavior и framing. Полезен для того же BSP-драйвера, который позднее пойдёт на аппарат; точность ограничена спецификацией и тестами, не скоростью исполнения TCG.
3. **Аппаратно подтверждённая модель:** модель сопоставлена с разрешёнными измерениями конкретной ревизии; перечислены совпадения и расхождения. **Сейчас таких подтверждений нет.**

Каждая подсистема получает уровень и evidence отдельно. Картинка 240×320 в окне, синтетический incoming call или успешная загрузка ядра не поднимают весь эмулятор на уровень аппаратной точности. Cycle accuracy, энергопотребление, аналоговый радиотракт, ёмкость старого аккумулятора и все silicon errata не обещаются.

## Периферия Blue Angel: reuse / adapt / new / unknown

Классификация — инженерная оценка по источникам. **Реализованный результат E2A/E2B ограничен CPU proxy/RAM/diagnostic UART/timer/PIC/GPIO90 и functional MMU probes**; остальные строки остаются планом. `reuse` означает кандидата общего механизма, `adapt` — проверку/изменение модели, `new` — отдельную модель/board wiring, `unknown` — отсутствие достаточного контракта.

| Узел | Оценка | Доказанный источник / граница reuse | Что ещё необходимо |
|---|---|---|---|
| **CPU PXA263 / XScale ARMv5TE** | reuse TCG ARMv5 + **adapt/new**, точность unknown | Q91 `target/arm/tcg/cpu32.c`; Q92 inventory: PXA263 отсутствует | Подтверждённый CPUID, CP14/15, reset state, cache/MMU quirks и отличия PXA26x. E2B CP15/MMU и UNDEF для CP14 CLKCFG/PWRMODE проверены; cache maintenance NOP. Точный PXA263 и полный CP14/15 остаются unknown |
| **SDRAM и MMU** | reuse MemoryRegion/ARM MMU + adapt | Q91 `hw/arm/pxa2xx.c:2249–2256`, `include/hw/arm/pxa.h`; [BOOT.md](../BOOT.md) | Банки 128 MB, aliases/holes/reservations и handoff contract Blue Angel; тесты data/prefetch abort, permissions, page walk. E2A synthetic128MiB и E2B section page walk/Client DACR/alias проверены. RAM retention через warm reset synthetic; физические банки, полная MMU permission/fault matrix, частота RAM и refresh timing отдельно unknown |
| **Flash / внутреннее хранение** | reuse generic CFI + **new/adapt**, topology unknown | Q91 `hw/block/pflash_cfi01.c`; BA `blueangel.c:719–783`, `include/mach/blueangel.h` указывают StrataFlash и Doc G3 | Реальная комплектация/command set/width/ID/geometry. Размер `nk.nbf` не физическая геометрия. Сначала synthetic read-only image; WM ROM не требуется и не распространяется |
| **ATI Imageon W3200 / LCD 240×320** | **new**, generic display backend reuse | BA `blueangel.c:315–508,1097–1100`; `drivers/video/w100fb.c` | Следующая работа — исследовать ATI aperture, framebuffer placement/stride/format, panel variant, clocks/reset/IRQ; модель пока не реализована. Q91 `hw/display/pxa2xx_lcd.c` эмулирует **встроенный PXA LCD**, не внешний ATI; скопировать его MMIO нельзя |
| **TSC2200 touch + front keys** | **new/adapt**, SSI/input infrastructure reuse | BA `blueangel.c:843–902`, `drivers/spi/tsc2X0X-core.c`, `drivers/input/touchscreen/tsc2X0X_ts.c` | SPI register contract, conversion scheduling, ADC calibration/pen IRQ/front-key bitmap. Q91 `hw/input/tsc210x.c` создаёт TSC2102/2301; `tsc2005.c` — иной чип. Их наличие не означает TSC2200 support |
| **ASIC3 и sliding QWERTY** | **new**, GPIO/IRQ/SSI infrastructure reuse | BA `blueangel.c:202–314,905–1021`; `drivers/mfd/asic3.c`, `drivers/input/keyboard/htc-asic-kbd.c` | ASIC register map/16-bit bus shifts, cascaded IRQ, keyboard SPI FIFO/reset/scancodes/Fn/repeat. Mainstone PXA27x keypad не подходит. Кириллица — отдельный слой раскладки |
| **SD / SDIO** | SD card backend reuse; **new/adapt controller** | BA `blueangel.c:288–295`: ASIC3 SD region/IRQ; `drivers/mfd/asic3.c:800–809`: `tmio-mmc`. Q91 `hw/sd/sd.c` — generic card | Не заменять ASIC3/TMIO контроллер на PXA MMCI из Connex. Проверить регистры/clock/card detect/IRQ/DMA; SDIO functions отдельно unknown. Использовать только файлы synthetic SD, не physical media |
| **UART** | reuse generic serial + adapt/wiring | Q91 `hw/arm/pxa2xx.c:2291–2298`, `hw/char/serial.c`; BA `blueangel.c:786–806` | PXA-specific bits/FIFO/flow control/clock/IRQ. E2A generic diagnostic UART проверен отдельно. FFUART у Blue Angel связан с GSM data; physical wiring/PXA-specific control не подтверждены этой диагностикой |
| **Timers / IRQ / DMA / GPIO** | reuse/adapt | Q91 `hw/timer/pxa2xx_timer.c`, `hw/dma/pxa2xx_dma.c`, `hw/arm/pxa2xx_pic.c`, `pxa2xx_gpio.c`; BA `blueangel.c:1113–1122` | E2A четыре timer/PIC, clock/match/mask/ack/routing и reset проверены. E2B GPIO90, включая 86–89, и PIC8/9/shared10 проверены. AF edge gate — явная интерпретация subset; DMA/ASIC cascades, descriptor bounds/cache visibility ещё не реализованы; Linux virtual IRQ не аппаратный номер |
| **Power / RTC / sleep / battery** | adapt SoC + **new functional model**, analog unknown | Q91 `hw/arm/pxa2xx.c` PM/RTC; BA `blueangel.c:608–717,1075–1088`, `drivers/mfd/asic3.c` | Reset/wake/retention/AC events, callbacks и сохранение модели. Закомментированный Linux wake config не спецификация. Заряд/ток/напряжение только синтетические входы с явной меткой |
| **Audio / UDA1380 / modem route** | generic audio backend reuse; **new/adapt** | BA `blueangel.c:1026–1041`, `sound/soc/pxa/blueangel.c`; Q91 PXA I2S в `hw/arm/pxa2xx.c` | Codec I2C, SSP/I2S paths, DMA, mute/route/power/wake. Тон из host speakers не доказывает телефонный аудиотракт |
| **Wi-Fi** | **unknown/new** | [HARDWARE.md](../HARDWARE.md), BA board GPIO имена — только кандидаты | Чип/ревизия, bus/IRQ, firmware boundary и протокол. Ethernet SMC91C111 Gumstix не замена Wi-Fi Blue Angel |
| **Bluetooth** | **unknown/new**; generic serial backend candidate | BA `blueangel.c` GPIO/pinmux — контекст, не полный transport | Точный controller/firmware, UART/flow/reset/wake. Host Bluetooth passthrough не часть первоначального проекта |
| **IrDA** | adapt PXA FIR + **unknown board wiring** | Q91 `hw/arm/pxa2xx.c` FIR; BA `blueangel.c:148–154` и GPIO uncertain comments | SIR/FIR/transceiver gating и UART sharing. Эмулировать кадры после доказательства, без настоящего ИК-устройства |
| **GSM / DPRAM / Calypso** | **new**, protocol unknown; functional mock отдельно | BA `blueangel.c:786–806`, `htc_calypso.c`; ROM-кандидаты в [RESEARCH_NEXT.md](../docs/RESEARCH_NEXT.md) | FFUART data/DPRAM control не задают framing/handshake/commands. До извлечения и сверки протокола register-level modem не заявлять |

Поиск имён в полном дереве Q91 (10 836 путей, ответ без truncation) сохранён [отдельно](evidence/qemu-9.1.0-tree-search.json): есть PXA/TSC210x/TSC2005, нет именованных Blue Angel/ASIC3/W3200/TSC2200/Calypso/TMIO моделей. Это ограниченный поиск имён; он не доказывает отсутствие всех пригодных компонентов. Исходники уже содержат `TODO reset peripherals` (`pxa2xx.c:2091`) и неполные режимы LCD, поэтому reuse обязательно проходит собственные reset/error tests.

## GSM test model: звонки, SMS и пробуждение

**Предложение, пока без реализации.** Сделать два разных уровня подключения к общему сценарию:

- `functional` adapter в тестовой конфигурации Crosshair принимает логические Dial/Answer/Hangup/SendSms и выдаёт CallState/IncomingSms/Registration/Wake. Этот интерфейс — наш тестовый контракт, не Windows RIL и не известный protocol Calypso.
- Будущий `blueangel-dpram` adapter подключает тот же сценарий к доказанным регистрам/буферам/IRQ и FFUART. Его реализация начинается после восстановления DPRAM framing/ownership/handshake из первоисточников. Нельзя заранее посылать AT-строки в вымышленные DPRAM offsets или считать текстовый `RING` доказанной URC реального Blue Angel.

Общая модель хранит отдельно network registration, call lifecycle, SMS transactions/queue и sleeping/wake policy. Звонки: idle → dialing/alerting → active → releasing → idle; incoming → ringing → answer/reject/missed; занято, удалённый hangup и потеря регистрации имеют явные причины. Hold/resume добавлять только с описанной семантикой. SMS различают принятие исходящего сообщения моделью, доставку адресату, delivery report и входящее сообщение; проверяются storage-full, дубликаты, задержки, ошибки encoding и multipart metadata. Модель не обещает реальную GSM-сеть.

Детерминированность задаёт тестовый scheduler: виртуальное время `u64 ns` от нуля; очередь `(deadline_ns, insertion_sequence)` с фиксированным порядком для совпавших deadline; отмена события по token, фиксированный seed для управляемых отказов, все входы и config сохраняются в trace. Переполнение времени/sequence — явная ошибка. Никаких wall-clock sleeps, случайных настоящих входящих, SIM, operator access или внешнего сетевого backend.

Для QEMU device tests использовать QTest clock stepping (`Q91:system/qtest.c:77–100`, `docs/devel/qtest.rst`) и QEMU virtual timers. Для исполнения CPU отдельно проверить режим TCG/icount и полный контроль host inputs; один `-icount` не делает произвольный GUI/audio/network сценарий детерминированным (`Q91:docs/devel/replay.rst`). Pause VM не продвигает сценарий; CPU sleep и ход периферийного/wake clock описываются отдельно. IRQ-level latch, masked interrupt, repeated notification и очистка pending моделируются явно. До DPRAM-адаптера Wake — логическое событие mock; физическая линия остаётся неизвестной.

Обязательные будущие сценарии: исходящий/входящий звонок с hangup с обеих сторон; answer одновременно с timeout; incoming во сне и wake при masked IRQ; SMS до/во время/после звонка; lost/duplicate/reordered unsolicited events; частичный transport frame; modem reset; perpetual busy; delayed response; FIFO overflow; пропавший wake. URC здесь означает класс асинхронных уведомлений модели, а не установленный синтаксис модема. Каждый сценарий завершается assertion состояния, pending timers/IRQs, bounded queues, timeout результата и отсутствие зависания.

## Предел полезности и открытые вопросы

E2A/E2B проверяют базовое исполнение ядра, timer/GPIO/IRQ, functional MMU и error paths. Программный renderer/UI уже развивается [отдельно](../docs/UI_0.2.md) и не подтверждает ATI MMIO; W3200 contract требует исследования. Аппаратный клавиатурный workflow и телефонная логика остаются дальнейшими направлениями. Для тестирования настоящего Blue Angel BSP нужны register-level contracts. Загрузка заводской ROM не является критерием первых этапов: исходный образ отсутствует, а совместимость загрузчика, ASIC и undocumented accesses неизвестна.

Главные блокеры точности: PXA263 CPU/SoC различия; аппаратная ревизия и карта памяти; ATI/ASIC3/TSC2200 доступные спецификации; восстановление M1 `QwertyKey.dll`; DPRAM modem protocol; power/wake/audio contracts. Поздние golden traces получать только по отдельно разрешённой процедуре на КПК, с сохранением исходной WM и данных; до этого эталоны синтетические и отмечены как таковые. Эмуляция не подтверждает электрическую безопасность или аппаратную готовность драйвера.
