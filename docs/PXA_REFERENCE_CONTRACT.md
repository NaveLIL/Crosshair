# QEMU 9.1: контракт исследовательского PXA guest

Дата: 16.10.2026. Все адреса ниже относятся к **программным моделям QEMU**, не к подключённому PDA2k. Connex/PXA255 и Verdex/Mainstone/PXA270 не являются Blue Angel/PXA263. Точность периферии и электрические характеристики настоящего устройства этим исследованием не подтверждаются.

**Результат этого документа — подтверждённый исходниками контракт и программа проверки.** Исполнение нового Rust guest, приём аппаратных IRQ гостем и QTest результаты нельзя объявлять выполненными только по этому документу; их отдельные журналы должен создать E1 runner. Существующий Boot 0.1 VersatilePB к этому не приравнивается.

## 1. Закреплённый первоисточник

Здесь **Q91** всегда означает QEMU v9.1.0, commit [`fd1952d814da738ed107e05583b3e02ac11e88ff`](https://github.com/qemu/qemu/tree/fd1952d814da738ed107e05583b3e02ac11e88ff). Пути/строки в таблицах относятся только к нему. Основной source manifest расположен в `crosshair-emulator/evidence/qemu-source-manifest.json`. Для этой работы дополнительно прочитаны boot loader, generic loader, serial, CPU reset и QTest sources; файлы из локального архива побайтно сверены с raw-файлами этого commit через HTTPS.

| Дополнительно сверенный файл | SHA-256 |
|---|---|
| `hw/arm/boot.c` | `6a602beecc7a632481d4352da3ca3b94f53ced888062bcf54dedc2244fd3cfa9` |
| `hw/core/generic-loader.c` | `be2c003200ac4dd7967439a31529096c8998ea40b5ad20d867fa2318777c127a` |
| `hw/core/loader.c` | `e24842d172d181c6e3b11f6a4e2598d679444efc66ff83cd2ff65ef7fc3fa113` |
| `hw/char/serial.c` | `4d591a0162c9402b3539712c74fe026f0c0ceb6f04d30776ac78dc60cf1b896c` |
| `target/arm/cpu.c` | `74a38b1975ada88ffafc6f49dea2344fd39d9b09567c61df220fb40dd1af83ba` |
| `include/hw/arm/pxa.h` | `3ff5532373ddcc6d9443597d89de246b9998016cdd25f8bc28f5a05bac3e723c` |

Исследовательская копия этой сессии: `/tmp/crosshair-q91-contract/qemu-9.1.0/`. Не переносился исходный код QEMU в Rust guest. QEMU сохраняет свои notices и лицензию; собственный код Crosshair распространяется по MIT, сторонние исходники сохраняют свои условия.

## 2. Память и передача управления

| Machine | CPU / физическая RAM модели | Путь загрузки собственного образа |
|---|---|---|
| `connex` | Жёстко создаётся `pxa255`; SDRAM `[0xa0000000,0xa4000000)` = 64 MiB; internal RAM `[0x5c000000,0x5c040000)` | `gumstix.c:56–77` **не вызывает `arm_load_kernel`**. Само наличие `-kernel` не создаёт работающего загрузочного пути. Нужен generic loader либо собственный firmware. |
| `verdex` | default `pxa270-c0`; SDRAM `[0xa0000000,0xb0000000)` = 256 MiB; internal RAM те же 256 KiB | То же отсутствие `arm_load_kernel`, `gumstix.c:79–100`. Для E1 нужен generic loader. |
| `mainstone` | default `pxa270-c5`; SDRAM `[0xa0000000,0xa4000000)` = 64 MiB; internal RAM 256 KiB | `mainstone.c:106–109,157–163` вызывает `arm_load_kernel`, loader_start `0xa0000000`, Linux board_id `0x196`. Поддерживается `-kernel` с ELF через общий ARM loader. |

База SDRAM/internal подтверждена Q91 `include/hw/arm/pxa.h:67–69`; реальные MemoryRegion mappings — [`hw/arm/pxa2xx.c:2112–2119,2249–2256`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/pxa2xx.c#L2112). Фиксированные размеры задаются board code, а не произвольным `-m`: [`gumstix.c:48–52,61,84`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/gumstix.c#L48), [`mainstone.c:102–109,124`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/mainstone.c#L102).

Connex/Verdex при обычном запуске требуют host pflash backend, даже если guest загружается generic loader: `gumstix.c:63–73,86–96` проверяет отсутствие drive и завершает процесс, кроме QTest режима. Размеры flash модели — 16 и 32 MiB соответственно. Для теста подходит **новый синтетический локальный файл** без firmware производителя, подключённый readonly; физические накопители и пользовательская SD не нужны. Mainstone создаёт ROM/flash модели без обязательного внешнего pflash файла. Нулевой физический адрес в этих моделях нельзя считать writable SDRAM.

### ELF и raw — разные контракты

**Mainstone ELF:** Q91 [`hw/arm/boot.c:952–954`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/boot.c#L952) явно считает ELF образом не-Linux. ELF PT_LOAD загружаются по его адресам; entry берётся из ELF. В [`boot.c:685–723`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/boot.c#L685) CPU reset для этой ветки устанавливает PC в entry, не выполняя Linux boot stub. Поэтому `r0=r1=r2=0` после reset; `r1=0x196` **не является** контрактом ELF входа.

**Mainstone raw `-kernel`:** если ELF/uImage decoding не сработал, `boot.c:991–999` загружает raw по `loader_start+KERNEL_LOAD_ADDR` и считает его Linux. CPU начинает со stub в `loader_start`, который устанавливает `r0=0`, `r1=board_id`, `r2=argptr` и PC entry (`boot.c:83–95,754–764`). Не использовать raw и ELF как взаимозаменяемые способы теста регистров.

**Generic loader:** [`hw/core/generic-loader.c:139–160`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/core/generic-loader.c#L139) поддерживает ELF, затем uImage/hex, затем raw. Для ELF `addr` заменяется ELF entry; `cpu-num=0` включает установку PC после CPU reset (`46–55,100–105`). Без `cpu-num` файл загружается, но PC не меняется. `force-raw=on` требует явный адрес загрузки и не использует ELF header. Для Connex/Verdex предложение E1: один собственный ELF и `-device loader,file=guest.elf,cpu-num=0`. `r0–r2` остаются нулями reset, никакого HaRET/Linux handoff нет.

Примеры **шаблонов** запуска после создания и проверки собственного guest; наличие команд здесь не является журналом их исполнения:

```sh
"$QEMU91" -machine mainstone -cpu pxa270-c5 -accel tcg \
  -display none -monitor none -serial stdio -nic none -no-reboot \
  -kernel "$GUEST_ELF"

"$QEMU91" -machine connex -accel tcg \
  -display none -monitor none -serial stdio -nic none -no-reboot \
  -drive if=pflash,format=raw,file="$SYNTHETIC_CONNEX_FLASH",readonly=on \
  -device loader,file="$GUEST_ELF",cpu-num=0
```

Verdex использует такую же generic-loader схему с `-machine verdex -cpu pxa270-c0` и собственным 32-MiB синтетическим pflash файлом. `QEMU91` должен указывать проверенную сборку 9.1; версия и argv записываются в результат каждого теста.

## 3. CPU reset, vectors и настоящий IRQ handler

**ДОКУМЕНТ:** `pxa255` и все перечисленные PXA270 variants имеют `reset_sctlr=0x00000078` ([`target/arm/tcg/cpu32.c:817–826,917–940`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/target/arm/tcg/cpu32.c#L817)); reset cpreg берет это значение (`target/arm/helper.c:9823–9831`). В нём M, C, I, V выключены: MMU, D-cache, I-cache off, low vectors. CPU reset обнуляет регистры и устанавливает SVC с IRQ/FIQ masked ([`target/arm/cpu.c:234–237,353–374`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/target/arm/cpu.c#L234)). Это нужно также записать самим guest в RAM diagnostic record до изменения CP15/CPSR.

IRQ vector при low vectors находится по PA `0x18`; source exception implementation задаёт IRQ mode, addr `0x18`, LR offset 4 (`target/arm/helper.c:11339–11344`). Нельзя включать CPU IRQ, оставив неинициализированный банковый `sp_irq` и таблицу vectors в flash/ROM. Обычный branch `b handler` из VA0 в `0xa0008000` превышает диапазон ARM branch.

**ПРОЕКТ E1:** собственная короткая `.vectors` PT_LOAD по PA0, восемь `ldr pc,[pc,#0x18]` и восемь абсолютных target words по `0x20..0x3c`. IRQ slot `0x18` через literal `0x38` ведёт к собственному ARM wrapper в SDRAM. Остальные vectors ведут к bounded fault-record+halt; entry остаётся в SDRAM, например `0xa0008000`. Никакая ROM производителя не нужна.

Это допустимо загрузчику модели: raw `load_image_targphys_as` регистрирует ROM data (`hw/core/loader.c:125–140`), ELF loader регистрирует программы, а [`loader.c:1220–1268`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/core/loader.c#L1220) на reset использует `address_space_write_rom`, затем очищает instruction cache. Host loader может заполнить backing ROM/flash до guest без гостевых команд программирования flash. Фактическую видимость загруженного vector table по PA0 обязательно проверить в runtime; только source analysis этого не доказывает.

До `rust_main` выделяются независимые стеки SVC и IRQ, оба 8-byte aligned. IRQ stack и основная RAM record не пересекаются. В handler запрещены allocator, CE calls, panicking formatting и использование общего mutably borrowed UART из прерванного кода. Предлагаемый ARM wrapper без nested IRQ:

```asm
irq_vector:
    sub lr, lr, #4
    stmdb sp!, {r0-r12, lr}   /* 56 bytes: preserves 8-byte stack alignment */
    bl rust_timer_irq
    ldmia sp!, {r0-r12, pc}^  /* restore interrupted registers and CPSR from SPSR_irq */
```

Это программа реализации, пока не свидетельство выполненного теста. ARMv5 не имеет `cpsid/cpsie`: менять I/F нужно `mrs`/`orr` или `bic`/`msr cpsr_c`. Сохранение SPSR_irq этим wrapper корректно только при запрещённом nested IRQ и отсутствии переключения режима внутри Rust handler. Общие данные main/IRQ читаются в critical sections или через обоснованные raw volatile accesses; одного комментария о single CPU недостаточно для произвольных Rust reference aliases.

## 4. UART модели

| Контракт | Q91 source / значение |
|---|---|
| Первый serial backend (`-serial stdio`) | FFUART PA `0x40100000`, IRQ22. Таблицы `pxa2xx.c:36–49`, IRQ number `include/hw/arm/pxa.h:38`. UART создаётся только при наличии соответствующего `serial_hd(i)`. |
| Другие UART | BTUART `0x40200000`, STUART `0x40700000`; только PXA255 также HWUART `0x41600000`. Не нужны первому guest. |
| Шаг регистров | `serial_mm_init(...,regshift=2,...)`, `pxa2xx.c:2155–2160,2291–2296`: register number `n` расположен `base+4*n`. |
| Ширина / endianness | `serial_mm_read/write` переводят offset через `>>2`, используют 8-bit semantics и mask `value&255`; MemoryRegion разрешает до 8-byte access. Для guest выбрать aligned volatile **u32** и значения в младших 8 битах; не объединять несколько регистров в одну запись. `hw/char/serial.c:1000–1036`. |
| THR / DLL | `base+0x00`: THR при DLAB=0, divisor low при DLAB=1. |
| IER / DLM | `base+0x04`: interrupt enables при DLAB=0, divisor high при DLAB=1. |
| FCR / LCR / MCR / LSR / SCR | Offsets `0x08 / 0x0c / 0x10 / 0x14 / 0x1c`; THRE в LSR bit5, TEMT bit6. `serial.c:41,83,336–435,854–888`. |
| UART reset | `IER=0`, `LCR=0`, `LSR=0x60`, divisor `0x0c`, `MCR=OUT2(8)`, `SCR=0`, IRQ lowered. `serial.c:854–888`. Не распространять это на каждый регистр/полный PXA hardware reset. |
| Baud base PXA255 | `14745600/16=921600`, divisor8 даёт ровно 115200; `pxa2xx.c:2295`, `serial.c:175`. |
| Baud base PXA270 | Код использует **`14857000/16`**, целочисленно 928562, divisor8 даёт 116070.25. Не исправлять эту константу в документации на привычную частоту и не заявлять ровно115200; `pxa2xx.c:2159`. |

Минимальная инициализация: LCR=0, IER=0, FCR=0x06 (clear RX/TX, FIFO disabled), LCR=0x80 (DLAB), DLL=8, DLM=0, LCR=3 (8N1), MCR=8. Перед каждым THR write ждать THRE с конечным пределом; перед окончательным PASS при необходимости дождаться TEMT. При timeout сохранить RAM failure record и halt.

**Ограничение модели:** здесь используется generic 16550 `serial_mm`, не полный PXA UART. IER сохраняет только `value&0x0f` (`serial.c:368–369`); PXA-specific UUE bit6 не валидируется. Успех этого UART guest не подтверждает clock gating, GPIO pinmux, электрические уровни и UART/GSM wiring Blue Angel. Для настоящего PDA нельзя переносить готовность этого UART без отдельной спецификации.

## 5. OS timer и PIC

Адреса/wiring: [`hw/arm/pxa2xx.c:2121–2131,2258–2267`](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/pxa2xx.c#L2258). IRQ source base `OST_0=26` задан `include/hw/arm/pxa.h:42`; OSMR0–3 подключены к PIC26–29. PXA270 channels4–11 находятся на отдельной линии7, первому test не нужны.

| MMIO | Значение / семантика модели |
|---|---|
| Timer PA `0x40a00000`, span4KiB | Общий OS timer. Предлагаемые доступы aligned volatile u32. |
| OSMR0–3 `+0x00,+0x04,+0x08,+0x0c` | Match values, запись пересчитывает qtimer deadlines (`timer.c:280–288`). |
| OSCR `+0x10` | 32-bit counter, рассчитывается из QEMU_CLOCK_VIRTUAL; запись устанавливает базу и пересчитывает deadlines (`196–198,310–314`). Использовать wrapping arithmetic. |
| OSSR `+0x14` | Event bits; W1C. Запись1 в установленный bit0 очищает его и опускает IRQ0; запись0 не очищает (`341–348`). |
| OWER `+0x18` | Watchdog/reset match3, первому test не нужен, оставить0 (`350–351,418–422`). |
| OIER `+0x1c` | Interrupt enable bits, test использует только bit0 (`338–340`). |
| PXA25x frequency | **3 686 400 Hz**, `hw/timer/pxa2xx_timer.c:57`, свойство `pxa25x-timer`. |
| PXA27x frequency | **3 250 000 Hz**, `timer.c:58,576–580`. Нельзя применять одну частоту ко всем трём machines. |
| PIC PA `0x40d00000`, span1MiB | MemoryRegion по `pxa2xx_pic.c:303–307`; нужны только первые регистры. |
| ICIP `+0x00` | IRQ pending = raw pending & enabled & ~FIQ routing (`pic.c:143–146`). |
| ICMR `+0x04` | Enabled mask; bit26 включает OS timer0 (`185–187`). |
| ICLR `+0x08` | Значение0 в позиции source означает IRQ routing, значение1 — FIQ; установить0 для всех test sources (`191–193`). |
| ICFP `+0x0c` | Pending routed to FIQ (`157–160`). |
| ICPR `+0x10` | Raw pending, независимо от ICMR (`161–164`). Это не W1C acknowledge register. |
| ICCR `+0x14` | CPU idle wake mask policy, не требуется busy-loop first test (`197–198`). |

Все частоты — source-confirmed частоты **модели**. Для физического PXA263 актуален отдельный manual/revision contract.

Timer deadline вычисляется unsigned delta: `now_ns + floor((uint32_t)(match-now_counter)*1e9/freq)` (`timer.c:118–132`). Timer0 tick выставляет OSSR и IRQ **только если соответствующий OIER bit уже1** (`408–416`). Запись OIER сама не пересчитывает старый пропущенный deadline. Поэтому устанавливать compare достаточно в будущем и не делать тест на match, прошедший до включения OIER. Для repeat test явно переустанавливать OSMR0 в handler; первые четыре timers не реализуют здесь произвольный автоматический periodic mode.

## 6. Программа гостевого теста UART + timer IRQ

**ПРОЕКТ:** один собственный Rust `no_std` ELF с отдельными configs PXA25x/PXA27x; частота выбирается явно board config, а не угадывается из общей строки ARMv5. Runtime test должен проходить по реальному CPU IRQ exception path.

1. Сохранить входные r0–r2, CPSR, CP15 SCTLR/MIDR; установить SVC/IRQ stacks и собственные vectors; очистить BSS. Проверить initial MMU/cache bits и stack bounds, иначе record failure+halt.
2. Инициализировать модель UART, вывести `CROSSHAIR PXA ... START`. По-прежнему IRQ/FIQ masked; handler не выводит строки UART.
3. Явно инициализировать timer/PIC: `ICMR=0`, `ICLR=0`, `OIER=0`, `OWER=0`, `OSSR=0x0f`, `OSCR=0`. Чтением подтвердить OIER0/OSSR0. У PXA270 не трогать дополнительные counters4–11 без необходимости.
4. Установить period10ms: ticks=36864 на Connex или32500 на Verdex/Mainstone. `OSMR0 = OSCR.wrapping_add(ticks)`, затем `OIER=1`, `ICMR=1<<26`. Проверить programmed match в RAM record. Только после этого очистить CPSR.I; FIQ оставить masked.
5. IRQ wrapper вызывает `rust_timer_irq()`. Handler проверяет `(ICIP & (1<<26))!=0` и `(OSSR &1)!=0`; неожиданный IRQ фиксирует failure и выключает его. Захватить OSCR и номер IRQ entry, записать `OSSR=1`, подтвердить deasserted source, увеличить counter, записать timestamp. До третьего события: `OSMR0=OSCR.wrapping_add(ticks)`. На третьем: `OIER=0`, `ICMR=0`, установить done. Возврат через SPSR_irq восстанавливает main context.
6. Main ждёт `done` в bounded OSCR-based timeout, например1секунда виртуального counter, с wrapping subtraction. Перед оценкой результата маскирует IRQ. Требует ровно3 IRQ entries, source26, возрастающие timestamps по wrapping deltas. При сопоставлении с периодом учитывать до одного counter tick раннего срабатывания из-за floor-to-ns преобразования модели: нижняя граница `ticks-1`, а не безусловная `ticks`. Не требовать побитово одинакового wall-clock latency; upper bound устанавливать по своему явному timeout.
7. После masked IRQ убедиться `OSSRbit0=0`, `ICIPbit26=0`, `ICPRbit26=0`, `OIER=0`, `ICMR=0`; UART выдаёт фиксированный PASS один раз; final record содержит counts/timestamps/error=0 и stage idle. CPU уходит в контролируемую ARM ветку. Failure и unexpected exceptions всегда дают отличимые stage/error и ограниченный halt.

Host smoke одновременно требует конкретные UART bytes и конечный RAM record; PC должен находиться в idle, CPSR SVC/I/F masked, MMU/cache off, steки в собственных bounds. Наличие callback count в QTest или удачный QMP read сами по себе **не заменяют** гостевой exception entry/return. Прерванные регистры дополнительно проверяются guard значениями main, если runner предоставляет такой тест.

## 7. Независимая QTest проверка модели и reset

Для software device tests запускать отдельный процесс с **`-accel qtest`** и `-qtest unix:SOCKET,server=on,wait=off`. Тестовый accelerator использует dummy vCPU thread и собственный virtual clock: `accel/qtest/qtest.c:39–50,65–70`. `qtest_enabled()` — это `qtest_allowed` (`include/sysemu/qtest.h:19–23`); один socket при TCG не включает QTest clock stepping. На Gumstix QTest разрешает не передавать pflash файл. `-serial null` нужен, если проверяется наличие первого UART MMIO.

Протокол newline request/response; обрабатывать asynchronous messages до `OK`. Команды `writel/readl` обращаются к **модели**, `clock_step NS` монотонно двигает QEMU_CLOCK_VIRTUAL (Q91 `system/qtest.c:77–101,712–726`). Предлагаемые assertions:

- Initial process: UART LSR0x60, IER0, SCR0; PIC ICMR/ICLR/ICPR0; timer OIER0, OSSR0, OSCR0 при старте виртуального времени0.
- UART SCR: сохранить, записать0xa5/readback, восстановить. Перепроверить `LCR.DLAB` alias DLL/DLM без вывода в реальный serial backend.
- Frequency: установить OSCR0, `clock_step 1000000000`; OSCR должен быть ровно3686400 или3250000 соответственно. Это проверка частоты device clock, не частоты исполнения CPU.
- Match при PIC masked: OIER1, compare current+10ms, ICMR0; после clock_step10ms OSSRbit0 и ICPRbit26 установлены, ICIPbit26=0. Затем ICMRbit26 → ICIPbit26=1. `OSSR=0` не очищает; `OSSR=1` очищает event и pending. Другие raw pending bits фиксируются отдельно.
- Routing: повторить match с ICLRbit26=1 и ICMRbit26=1; ICFPbit26=1, ICIPbit26=0; затем W1C acknowledge. Это проверяет PIC routing, не вход FIQ guest.
- Mask after pending: убедиться, что ICMR=0 скрывает ICIP, сохраняя ICPR до timer W1C. Повторить match после clear — source должен сработать повторно.
- QMP `system_reset`: записать изменённые ICMR/ICLR, UART SCR/LCR и timer match/OIER/OSCR; после reset сохранить полную таблицу регистров. PIC pending/enabled/FIQ arrays и UART SCR/LCR reset подтверждены соответствующими reset functions. Для timer не требовать фиктивного полного reset: limitation ниже нужно зафиксировать как наблюдение модели.

**Подтверждённое source ограничение reset:** `hw/timer/pxa2xx_timer.c:455–498` инициализирует timer state только при создании; class `598–604` не регистрирует reset handler. PIC reset (`hw/arm/pxa2xx_pic.c:275–285`) очищает pending/enabled/FIQ arrays, но не всю priority/idle state. GPIO-driven PXA reset в `pxa2xx.c:2085–2092` вызывает `cpu_reset` и прямо содержит TODO reset peripherals. Поэтому warm reset этих старых models не является полным доказательством silicon reset. Для воспроизводимого E1 boot — новый процесс QEMU плюс явная инициализация используемой периферии; reset incompleteness отражать в evidence, не скрывать под общим PASS.

## 8. Условия завершения E1

Нужны отдельные verified version/build provenance, UART+IRQ guest evidence для каждой выбранной machine и независимые QTest traces частоты/mask/W1C/routing/reset. В каждой записи — hashes именно исполненного ELF и source/config, полный argv, machine/CPU/MIDR, virtual-time observations и явный статус skipped/failure. Из этой работы не следует, что guest уже выполнен: здесь проверены источники и спроектированы assertions. Ближайший шаг — реализовать и запустить описанный собственный guest на собранном Q91, начиная с Mainstone ELF, затем Connex generic loader.
