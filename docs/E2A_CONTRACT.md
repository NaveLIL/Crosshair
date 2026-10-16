# E2A: Minimal Virtual Blue Angel

Это собственная экспериментальная machine `crosshair-blueangel-e2a` на QEMU **9.2.0**, с CPU **pxa260**, а не точный PXA263. [Проверка различий CPU](E2A_CPU_PROFILE.md). Реальная плата HTC не использовалась; нет её ROM, Flash controller, GPIO, ASIC3, LCD, GSM, SDIO, Wi-Fi или audio. Проверка исполнения и фактические результаты — [отчёт](../reports/E2A_MINIMAL_BOARD.md).

## Память и вход

Все адреса ниже — **физические адреса экспериментальной модели**.

| Диапазон | Реализация и статус |
|---|---|
| `0x00000000..0x0000003f` | 64-byte synthetic vector RAM, загружаемый host ELF loader. Собственные восемь ARM vector entries и восемь absolute targets; нет factory bootloader |
| `0xa0000000..0xa7ffffff` | 128 MiB contiguous RAM, выбранный model contract. Реальные банки, aliases и WM reservations этим не устанавливаются |
| `0xa0008000` | Entry собственного ELF; два раздельных PT_LOAD региона для vectors/RAM. Flat RAM binary и `vectors.bin` отдельно, без многогигабайтного gap |
| `0x40100000` | Test-only generic 16550 diagnostic UART, stride4, byte/word access; не модель Calypso/Blue Angel serial wiring |
| `0x40a00000` | Четырёхканальный timer subset, aligned32-bit accesses |
| `0x40d00000` | PIC subset, aligned32-bit accesses |

Формат загрузки: QEMU generic loader `-device loader,file=...elf,cpu-num=0`. Это host parser ELF, а не контракт HaRET и не аппаратный Boot ROM. CPU reset имеет модельные MMU/cache off и low vectors; entry устанавливает IRQ-stack4KiB, SVC-stack16KiB, CPSR `0xd3`, очищает BSS и вызывает Rust. IRQ trampoline сохраняет C caller-saved registers, AAPCS alignment и возвращает SPSR через `ldmia ... pc^`. Ядро остаётся `no_std` ARMv5TE soft-float без Linux runtime, heap или GPL кода.

После трёх реальных IRQ26 гость подтверждает счётчик, status/pending, acknowledge и маски, печатает `CROSSHAIR E2A — UART TIMER IRQ PASS`, затем terminal idle. Это busy wait с IRQ/FIQ masked, не экономичный сон. Раздельные diagnostic features повторно используют проверенный E1 guest/assembly; E1 feature сохраняет прежние loadable bytes.

## Timer и PIC

Адреса/частота/source bits основаны на закреплённых Intel/PXADroid источниках в CPU profile. Полнота регистров, реализация reset и error behavior — явный контракт нашего ограниченного эмулятора. Это **register-level subset**, аппаратное подтверждение отсутствует.

| Offset timer | Регистр | Поддержка |
|---|---|---|
| `00/04/08/0c` | OSMR0..3 | RW, 32-bit matches |
| `10` | OSCR | RW, wrapping32 counter, 3 686 400Hz virtual clock |
| `14` | OSSR | Read latched low4 bits; write1 clears соответствующий event |
| `1c` | OIER | RW low4 bits; match при выключенном enable не устанавливает event |
| прочие | Включая OWER `18` | Unsupported: transaction error, а не успешное чтение0 |

Timer0..3 подключены к PIC sources26..29. После latched OSSR отключение OIER сохраняет источник до W1C: это интерпретация описанного Intel status-routing, согласующаяся с E1, без аппаратного измерения. PIC: ICIP `00` RO, ICMR `04` RW, ICLR `08` RW, ICFP `0c` RO, ICPR `10` RO. Raw source хранится отдельно от mask/routing; ICMR управляет IRQ/FIQ outputs, ICLR выбирает FIQ для установленного бита. Другие PIC offsets unsupported; ICCR/priority/second bank не реализованы.

Полный **model reset** обнуляет все четыре compare, OSCR/OSSR/OIER, PIC mask/route/pending, опускает IRQ/FIQ и отменяет старые callbacks. Нулевые compare при counter0 планируются на следующий wrap, а не немедленный event. Семантика reset здесь проверяет восстановление нашего state, не все виды reset PXA263.

Unsupported timer/PIC offsets, write-to-RO и неверная ширина/выравнивание завершаются `MEMTX_ERROR`. Machine не игнорирует memory transaction failures: CPU должен получить настоящий data abort. QTest протокол сам по себе не передаёт `MemTxResult`, поэтому отдельный отрицательный **TCG guest** проверяет DFSR external-abort, DFAR, собственный abort vector, stage5 и terminal idle. Просто увидеть0 в QTest недостаточно. Negative-test selector лежит в собственной синтетической RAM PA `0xa0000100` вне ELF/BSS: host loader пишет туда номер1..4. Его нельзя помещать в ELF `.data`, поскольку QEMU ROM reset восстановит исходное значение после data-loader reset hook. Это проверенный тестовый mailbox, не резерв реального устройства.

## Воспроизведение

```sh
scripts/bootstrap-rust.sh
scripts/bootstrap-qemu-blueangel.sh
scripts/test-e2a.sh
```

Если QEMU собран вне checkout, задать `QEMU_BLUEANGEL=/absolute/path/qemu-system-arm`. Bootstrap поддерживает отдельный `CROSSHAIR_QEMU_BLUEANGEL_DIR`; эталонные QEMU9.1 и vanilla9.2 не модифицируются. Сборка и QTest требуют тех же host dependencies, что [BUILDING](../BUILDING.md).

Результаты: `target/artifacts/e2a/{normal,mmio-test}/` — ELF, raw image, vectors, SHA256/ELF report/disassembly; `e2a-tests/` — actual TCG UART, QMP CPU/record, reset reboot и четыре abort probes; `e2a-qtest/` — virtual-time protocol, точные IRQ/FIQ transitions, register reset, invalid-MMIO side effects. TCG стартует с `-S`: QTest server используется только для physical RAM poison/readback после reset, затем QMP `cont` запускает настоящий ARM-код. Это отдельный режим от QTest accelerator suite, где инструкции не исполняются. Тесты завершают только созданные ими QEMU processes.

Host QEMU C и patch находятся в отдельной [GPL области](../crosshair-emulator/qemu/README.md). Ядро и test harness остаются MIT. Инструменты/образы производителя не публикуются.
