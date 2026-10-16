# crosshair-emulator E1: исполняемый PXA baseline

Дата: 16.10.2026. **Реализовано и проверено:** отдельный собственный ARMv5TE Rust-гость исполняется на трёх исторических моделях QEMU9.1; независимые QTest проверки описывают регистровые свойства и обнаруженные ограничения. Это не модель Blue Angel и не аппаратный запуск PDA2k.

## Результат исполнения

```text
PASS connex: UART, three real timer IRQs, exception return to SVC, two stacks, terminal idle
PASS verdex: UART, three real timer IRQs, exception return to SVC, two stacks, terminal idle
PASS mainstone: UART, three real timer IRQs, exception return to SVC, two stacks, terminal idle
```

Гость выводит `CROSSHAIR PXA REFERENCE — UART TIMER IRQ PASS` после трёх настоящих исключений IRQ, подтверждённых обработчиком в Rust. Хост не подставляет эту строку вместо гостя.

| Machine | QEMU CPU / ожидаемый MIDR | Timer frequency, независимо проверенная QTest | Загрузка |
|---|---|---|---|
| Connex | PXA255 / `0x69052d00` | 3 686 400 Hz | Generic ELF loader, synthetic 16 MiB pflash |
| Verdex | PXA270-C0 / `0x69054114` | 3 250 000 Hz | Generic ELF loader, synthetic 32 MiB pflash |
| Mainstone | PXA270-C5 / `0x69054117` | 3 250 000 Hz | Non-Linux `-kernel` ELF path |

Векторы располагаются в отдельном 64-byte PT_LOAD PA0; абсолютные `ldr pc` переводят исполнение в SDRAM. Основной entry PA `0xa0008000`, свой SVC stack16 KiB и IRQ stack4 KiB. Обработчик сохраняет caller-saved registers и adjusted LR, возвращается через `ldm ... pc^` с восстановлением SPSR. Main читает IRQ-owned record внутри критической секции, отключает источники и заканчивает в SVC с IRQ/FIQ masked. BSS перед исполнением намеренно испорчен generic loader; entry сам его очищает.

Гость явно инициализирует таймер/PIC, использует interval65 536 ticks, ограниченный цикл ожидания, source acknowledge через OSSR W1C, rearm после первых двух IRQ и отключение после третьего. В тесте учитывается округление deadline/counter в QEMU (один tick). QMP после сообщения проверяет PC=`kernel_idle`, CPSR low byte=`0xd3`, оба стека, MIDR, count=3, observed pending/status и очищенный источник. Ошибка/тайм-аут вызывает terminal panic; это не промышленная timer/IRQ driver model.

ELF/flat/vector bytes и хеши: [image.json](../crosshair-emulator/evidence/pxa-reference/image.json); [машинный код](../crosshair-emulator/evidence/pxa-reference/disassembly.txt). Сырой RAM `.bin` не включает векторы PA0; отдельный `vectors.bin` предотвращает создание flat файла размером более 2 GiB. ELF содержит оба региона.

## Независимые QTest результаты

Все три запуска: **`PASS_WITH_RECORDED_MODEL_LIMITATIONS`**. QTest использует dummy CPU; guest instructions не исполняются. QMP `cont` нужен для dispatch virtual timer callbacks, а перемещение времени задаётся только `clock_step`; PC до/после проверен неизменным. Это отдельное свидетельство поведения модели, не замена IRQ-гостю.

Проверены UART byte, ровно одна виртуальная секунда и counter frequency, 32-bit rollover, два независимых timer flags, OIER gating, OSSR W1C, raw PIC pending, ICMR masking и ICLR IRQ/FIQ routing. [Контракты и команды](../docs/PXA_REFERENCE_CONTRACT.md), [подробные QTest сценарии](../docs/PXA_QTEST.md).

**Обнаруженные ограничения QEMU9.1, не аппаратные гарантии:**

- `system_reset` сохраняет OSMR0/OSCR/OIER/OSSR, в то время как PIC pending/mask/routing обнуляются. Нет полного согласованного reset timer→PIC.
- Match при OIER=0 не устанавливает OSSR; позднее включение не восстанавливает событие. Отключение OIER после match не опускает уже поднятую IRQ; требуется OSSR W1C.
- UART — generic16550 с reg_shift2. UUE и clock gating PXA не обеспечены этой моделью; divisor8 не означает ровно115200 на PXA270.
- PXA263 отсутствует. PXA255/270 GPIO, CPU details и внешняя периферия не заменяют PXA26x/Blue Angel.

[Connex guest](../crosshair-emulator/evidence/pxa-reference/connex/smoke-test.json) / [QTest](../crosshair-emulator/evidence/pxa-reference/connex/qtest-result.json); [Verdex guest](../crosshair-emulator/evidence/pxa-reference/verdex/smoke-test.json) / [QTest](../crosshair-emulator/evidence/pxa-reference/verdex/qtest-result.json); [Mainstone guest](../crosshair-emulator/evidence/pxa-reference/mainstone/smoke-test.json) / [QTest](../crosshair-emulator/evidence/pxa-reference/mainstone/qtest-result.json). [Сводный манифест](../crosshair-emulator/evidence/pxa-reference/baseline-summary.json).

## Воспроизведение и база следующего этапа

```sh
scripts/bootstrap-rust.sh
scripts/bootstrap-qemu-pxa.sh
scripts/test-pxa-reference.sh
# Независимая регрессия существующего Boot0.1:
scripts/test.sh
```

QEMU9.1.0 pin: commit `fd1952d814da738ed107e05583b3e02ac11e88ff`, официальный tar SHA-256 `816b7022a8ba7c2ac30e2e0cf973e826f6bcc8505339603212c5ede8e94d7834`. Изолированный минимальный build включает GUMSTIX, MAINSTONE и GENERIC_LOADER. Последний потребовалось явно включить после первого runtime отказа; конфигурация исправлена и проверена. [Source/зависимости](../crosshair-emulator/evidence/pxa-reference/source.txt). QEMU9.2/VersatilePB сохранён. Здесь проверен macOS x86_64; Windows/WSL отдельно не запускались.

**Решение E1:** сохранить неизменённый QEMU9.1 как сравнительный baseline с тестами его ограничений. Для E2 выделить аудитируемый PXA26x subset и отдельную machine на более новой базе QEMU; текущая известная база Boot —9.2. Не делать весь Crosshair зависимым от необслуживаемых Gumstix/Mainstone, не переименовывать PXA255 в PXA263. На этапе переноса сначала проверяются reset/IRQ/timer/CP14/15/GPIO и происхождение GPL-кода; существующие тесты служат comparator, а не полной аппаратной спецификацией.

**Не выполнено:** реализация `crosshair-blueangel`, аппаратная калибровка, LCD/TSC2200/ASIC3, SD controller Blue Angel, modem protocol/model, power/sleep. M1 QwertyKey остаётся отдельным приоритетом; исходные ROM bytes по-прежнему отсутствуют. Ни физическая Flash, ни радио, ни SD/сам КПК не затрагивались.
