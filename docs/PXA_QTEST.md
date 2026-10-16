# Проверка моделей PXA через QTest

**Реализовано и проверено:** `tools/qtest_pxa.py` проверяет регистры реального процесса QEMU 9.1.0 для `connex`, `verdex`, `mainstone`. Все три платы прошли перечисленные проверки. Итоговый JSON имеет статус `PASS_WITH_RECORDED_MODEL_LIMITATIONS`: обнаруженное неполное поведение reset сохранено как ограничение, а не включено в утверждение об исправном сбросе оборудования.

QEMU закреплён на upstream commit `fd1952d814da738ed107e05583b3e02ac11e88ff`; отдельную сборку создаёт `scripts/bootstrap-qemu-pxa.sh`. Тест использует QTest MMIO и управляемое виртуальное время. Образ гостя, фирменная ROM и физические накопители не передаются. У Gumstix требование файла pflash отключается самой upstream-моделью при `qtest_enabled()`; используется её пустое содержимое памяти.

```sh
scripts/bootstrap-qemu-pxa.sh
python3 tools/qtest_pxa.py
python3 tools/qtest_pxa.py --machine connex
```

При необходимости другой путь к тому же закреплённому QEMU задаётся через `--qemu` или `QEMU_PXA`. Версия и SHA256 исполняемого файла входят в каждый JSON.

| Проверка | Фактический результат |
|---|---|
| UART FFUART, база модели `0x40100000`, шаг регистров 4 байта | Запись в THR даёт ровно байт `0x51` в файл serial; THRE/TEMT установлены до и после передачи |
| OSCR за ровно `1 000 000 000` нс QTest | `connex`: `3 686 400`; `verdex` и `mainstone`: `3 250 000` |
| OIER, модельная семантика | Выключенный канал не создаёт OSSR event; последующее включение не восстанавливает пропущенное совпадение |
| PIC, база модели `0x40d00000` | ICPR хранит сырой источник timer0 в бите 26; ICMR управляет его видимостью в ICIP/ICFP |
| ICLR | Один и тот же ожидающий источник переводится из IRQ pending в FIQ pending и обратно маскируется ICMR |
| OSSR W1C | Запись нуля и единицы в другой бит сохраняет событие; запись единицы очищает нужное событие и соответствующий вход PIC; каналы 0 и 1 проверены независимо |
| 32-битное переполнение OSCR | При старте `0xfffffff0` и OSMR0=`0x10` счётчик оборачивается по модулю `2^32`, а совпадение после перехода через ноль создаёт событие |

Для запуска используется `-accel qtest -S`. Затем QMP `cont` разрешает обработку виртуальных таймеров: под `-S` их callbacks не выполняются, хотя чтение счётчика уже отражает `clock_step`. QTest использует [dummy CPU thread](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/accel/qtest/qtest.c#L67), который [ожидает сигналы и не исполняет гостевые инструкции](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/accel/dummy-cpus.c#L21). Поэтому QMP сообщает VM `running`, но ARM-код не исполняется. Дополнительно тест сравнивает PC до и после регистровых проверок. Отдельный тест `tools/smoke_pxa.py` проверяет исполнение нашего гостя через TCG.

После `system_reset` на всех трёх моделях получено одно и то же:

| Регистр | До reset | После reset |
|---|---|---|
| OSMR0 | `0x1234` | `0x1234` |
| OSCR | `0x1235` | `0x1235` |
| OIER | `1` | `1` |
| OSSR | `1` | `1` |
| ICMR / ICLR / ICPR | `0x04000000` | `0` |

**Подтверждено исходником и измерением:** у [pxa2xx-timer есть init/realize, но отсутствует reset callback](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/timer/pxa2xx_timer.c#L598). [PIC сбрасывается отдельным callback](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/pxa2xx_pic.c#L275). Остаток таймера поэтому переживает reset, а pending PIC теряется. Для чистых независимых сценариев тест создаёт новый процесс QEMU на каждую плату и явно инициализирует нужные регистры между проверками. `system_reset` не считается восстановлением исходного состояния всей модели.

Ещё одна измеренная особенность: запись OIER=0 после совпадения сохраняет OSSR и уже поднятый вход PIC до W1C. Это соответствует [OIER write](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/timer/pxa2xx_timer.c#L338) и [tick callback](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/timer/pxa2xx_timer.c#L408) закреплённой модели. Частоты заданы в [её константах](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/timer/pxa2xx_timer.c#L57), карта UART/timer/PIC и wiring — в [pxa2xx.c](https://gitlab.com/qemu-project/qemu/-/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/pxa2xx.c#L2121). Все адреса в этом отчёте относятся к этим эмулируемым SoC.

Артефакты каждого запуска находятся в `target/artifacts/pxa-qtest/{connex,verdex,mainstone}/`: `qtest-result.json`, протокол команд `protocol.log`, внутренний журнал QTest `qemu-qtest.log`, `qemu-uart.log`, `qemu-stderr.log`. Предыдущий успешный JSON удаляется перед запуском; при ошибке регистровых проверок новый получает `FAIL` с конкретной причиной. Ненулевой код Python останавливает общий скрипт проверки.

**Неизвестно / не проверялось:** соответствие всех этих модельных деталей реальному PXA263, сброс и электрическое поведение HTC Blue Angel, UART pinmux/clock gating/UUE, точность baud rate, физические IRQ/FIQ, энергосбережение и сброс периферии настоящего КПК. QTest не заменяет эти проверки и не доказывает работоспособность драйвера на устройстве.
