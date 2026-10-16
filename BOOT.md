# Crosshair Boot 0.1: контракт загрузки

Две отдельные конфигурации: **VersatilePB/ARM926** для исполняемого теста и **Blue Angel/PXA263** для собираемого HaRET-адаптера. Успех первой не является подтверждением второй. Конкретные результаты исполнения и хеши — [отчёт](reports/BOOT_0.1.md).

## VersatilePB

QEMU `9.2.0`, `-machine versatilepb -cpu arm926 -m 128M -accel tcg`. CPU ARM926EJ-S поддерживает ARMv5TEJ и выполняет наш ARMv5TE код. Это не модель PXA263 и не эмуляция самого PDA2k.

| Область / регистр | Значение | Основание |
|---|---|---|
| SDRAM | PA `0x00000000`, размер задаёт `-m 128M` | [QEMU v9.2.0 versatilepb.c:223–224](https://github.com/qemu/qemu/blob/v9.2.0/hw/arm/versatilepb.c#L223) |
| Размещение Crosshair | entry `0x00010000`; бюджет до PA `0x01000000` | Наш `link/versatilepb.ld`; сознательно оставлены первые 64 KiB |
| Диагностика | UART0 PL011 PA `0x101f1000`, serial backend 0 | [versatilepb.c:279](https://github.com/qemu/qemu/blob/v9.2.0/hw/arm/versatilepb.c#L279) |
| PL011 DR / FR | offset `0x00` / `0x18`; FR.TXFF bit 5 | [pl011.c:47–55,95–100](https://github.com/qemu/qemu/blob/v9.2.0/hw/char/pl011.c#L47) |
| PL011 baud/control | IBRD `0x24`, FBRD `0x28`, LCR_H `0x2c`, CR `0x30`, IMSC `0x38`, ICR `0x44`, DMACR `0x48` | [pl011.c](https://github.com/qemu/qemu/blob/v9.2.0/hw/char/pl011.c); 32-bit accesses, UARTEN bit0, TXE bit8 |

PL011 драйвер использует polling, IRQ/DMA отключены. Делители `13,1` соответствуют 24 MHz / 115200; QEMU char backend не доказывает точность физического baud или электроники. Источник UART clock Versatile — [Linux v6.6 versatile-ab.dts:27–30,240–245](https://github.com/torvalds/linux/blob/v6.6/arch/arm/boot/dts/arm/versatile-ab.dts#L240) (24 MHz fixed clock); для проверки bytes достаточно модели QEMU. Ошибка ожидания TXFF ограничена 1 000 000 чтений на байт; это лимит циклов, не измеренный wall-time timeout. Сбой UART фиксируется stage 4 и terminal idle.

QEMU загружает сегменты нашего **ELF** по PA и начинает с ELF entry в non-Linux path: [hw/arm/boot.c](https://github.com/qemu/qemu/blob/v9.2.0/hw/arm/boot.c). От Linux bootstub, ATAG, initrd, rootfs и semihosting этот запуск не зависит. Регистры r0-r2 при этом не интерпретируются как Linux ABI. Вход предполагает privileged ARM little-endian state, выключенные MMU и caches, загруженные `.text/.rodata/.data` и доступную RAM. Entry сам не пытается вслепую выключать неизвестную работающую MMU.

`src/arch/entry.S` без доступа к унаследованному стеку устанавливает CPSR `0xd3` (SVC, ARM, IRQ/FIQ masked), загружает 8-byte aligned SP из linker symbol, очищает BSS словами и вызывает Rust. r0-r2 сохранены до вызова. `.data` загружена на свой VMA=PA, отдельного relocation/copy-down нет. 16 KiB стека резервируются линкером; расход в худшем случае пока не измерен.

`rust_main` проверяет BSS и volatile initialized-data sentinel, сохраняет входные регистры, печатает UTF-8:

```text
CROSSHAIR BOOT 0.1 — HELLO FROM RUST
```

Затем ставит stage 2 в `CROSSHAIR_BOOT_RECORD` и входит в единственную ARM-инструкцию `b kernel_idle`. Это контролируемый busy wait с IRQ/FIQ masked, **не реализованное энергосбережение**. Никакого аллокатора, ОС хоста в госте, задач, таймеров или файловой системы нет. Exception vectors и banked exception stacks ещё не установлены; аппаратные abort/undefined instruction не обрабатываются как Rust panic.

Panic сохраняет stage 3 и сообщение `CROSSHAIR PANIC — HALTED`, пробует ограниченный UART вывод и также уходит в terminal loop. Отдельный feature `panic-test` проверяет этот путь реальным исполнением. Обычный BSP отдельно от ядра, PL011 driver отдельно от BSP. Все unsafe участки сопровождаются локальным контрактом.

Автотест сверяет SHA-256 текущих бинарников с манифестом и намеренно записывает `0xa5a5a5a5` в BSS stage через QEMU generic loader перед исполнением: успешный вход требует нашей очистки BSS. Ждёт точные UART bytes, затем QMP `stop` и `info registers`/`xp`: требует PC=`kernel_idle`, SP внутри своего 16 KiB стека с выравниванием 8, CPSR low byte=`0xd3`, magic=`0x43524f53`, ожидаемые stage/длину сообщения. Завершает только собственный QEMU process. Нет строк, напечатанных хостом вместо гостя.

## Blue Angel / HaRET

Подробный первоисточниковый разбор: [BLUEANGEL_BOOT_RESEARCH.md](docs/BLUEANGEL_BOOT_RESEARCH.md). Кратко: исследованный HaRET копирует сырой kernel file в `RAMADDR + 0x8000` и вызывает его начало с r0=0, r1=766, r2=`RAMADDR + 0x100`. Исторический PXA RAMADDR=`0xa0000000`, значит candidate entry PA=`0xa0008000`. Source-derived карта не доказывает безопасность перезаписи работающей RAM конкретного экземпляра.

Наш `blueangel` feature использует общий ARMv5 entry, свой linker origin и отдельный RAM-only logger. Выход — **flat binary**, не ELF для HaRET; начало файла соответствует `_start`, файл `crosshair-haret.bin` дополнен нулями до страницы 4096. Общий boot record и `BLUEANGEL_RAM_LOG` находятся внутри собственного BSS; нет обращений к UART/экрану/Flash/питанию PXA. Контракт HaRET о выключении MMU/caches исследован статически; точное соответствие скачанного EXE исходному commit не установлено. Образ собран и проверен как ELF/машинный код, на PXA/КПК не исполнен.

Из-за возможного исполнения `startup.txt` при открытии HaRET проект не создаёт готовый аппаратный startup с `boot`. Параметры и их значение перечислены в исследовании. Диагностический RAM log пока не имеет доказанного физического readback пути; он не делает аппаратный запуск наблюдаемым. FFUART исторического Linux связан с модемом: перенести туда PL011/debug console нельзя.

Возврат в ту же WM-сессию не предусмотрен контрактом. Сохранённая Flash не означает сохранённые данные: WM2003 хранит пользовательское состояние в RAM. Перед отдельным разрешённым аппаратным рубежом нужны backup с проверкой восстановления, сверенный loader, RAM reservations, диагностический канал и согласованная процедура reset/возврата к ROM. В этой задаче аппаратный запуск не выполняется.

## E2A: собственная экспериментальная machine

`crosshair-blueangel-e2a` использует QEMU9.2 CPU260 proxy, synthetic128MiB RAM и64B low-vector RAM. Generic ELF loader, entry `0xa0008000`, два стека, триIRQ26 и terminal idle проверены реальным исполнением, включая reset/reboot и четыре data-abort probes. Это отдельный [загрузочный контракт E2A](docs/E2A_CONTRACT.md), а не HaRET или заводская плата. [Протокол/сравнение E1](reports/E2A_MINIMAL_BOARD.md). E1 QEMU9.1 и его тесты сохранены.

## E2B: GPIO и функциональная MMU

`crosshair-blueangel-e2b` сохраняет RAM/vector/UART/timer/PIC контракт E2A и добавляет GPIO90 по PA`0x40e00000`. Только CPU260 proxy. Generic loader загружает собственный ELF с entry PA`0xa0008000`; ARM entry очищает BSS, создаёт SVC16KiB/IRQ4KiB stacks и различимые UNDEF/prefetch/data-abort vectors. Никакого OEM startup не используется.

Guest считывает reset CP15, проверяет cache-bit readback без заявления о физических cache, создаёт собственную16KiB-aligned L1, выполняет uncached section alias VA`0x20000200`→PA`0xa0000200`, восстанавливает MMU/control state. Затем GPIO direction/AF/preload и пять IRQ проверяются реальным TCG execution. Первый фронт приходит при masked PIC; guest проверяет сохранённый pending и нулевой IRQ count, снимает маску и обрабатывает событие. Host adapter подаёт уровни0/1/2/89; это не драйвер клавиатуры. После PASS — masked SVC idle. Тот же процесс проходит `system_reset` и повторный boot с проверкой очистки заранее испорченной BSS.

Три отдельных negative probes проверяют GPIO data abort и точный DFAR; ещё два — UNDEF на отсутствующих в этой composition CP14 CLKCFG/PWRMODE. Harness сверяет fault vector, LR/SPSR и реальные opcodes. Существование этих controls в аппаратном PXA26x не отрицается. [Audit и неподтверждённые свойства](docs/E2B_CPU_GPIO_AUDIT.md), [исполненные журналы](reports/WAVE_003.md). Сохранение RAM и внешних input levels через QEMU warm reset — synthetic contract; физический reset/HaRET handoff этим не подтверждены.
