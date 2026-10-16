# Следующие исследования Blue Angel: M1 и аппаратная спецификация

Дата: 16.10.2026. Это локальные статические исследования. На КПК ничего не запускалось; драйверы Blue Angel не реализованы и не проверены.

## Воспроизводимость

Полный ROM-анализ требует исходных EXE/NBA, отсутствующих в публичном репозитории. Исторические каталоги не являются текущим rerun. Parser проверен 19 синтетическими тестами, включая CAB backend и повреждённый ввод.

## M1 — отдельный первый приоритет: QwertyKey.dll

**Подтверждено предоставленным каталогом**, а не повторным чтением ROM в этой сессии:

| Поле | Значение и тип |
|---|---|
| Файловая TOC-запись | `nk.nba` offset `0x8b92e0` |
| Данные | `nk.nba` offset `0x634974`, длина 2 029 байт, конец exclusive `0x635161` |
| Исходный размер по TOC | 6 144 байта |
| Адрес из TOC | `load_va=0x806348f4`; адрес в модели ROM, **не адрес размещения Crosshair** |
| Область из TOC | `region_start=0x80400000`; не доказательство физической карты платы |
| Текущее состояние | Сжатый файловый объект; пригодного PE нет, кодек неизвестен |

Порядок завершения M1:

1. Получить локальный исходный EXE с указанным выше SHA-256 или сверенный `nk.nba`; повторить инвентаризацию в новый приватный каталог. Извлечь **ровно** `[0x634974, 0x635161)` в файл с расширением `.compressed`, сохранить SHA-256. По JSON нельзя получить исходные 2 029 байт или определить их кодек.
2. Установить формат сжатия по содержимому объекта, Windows CE соответствующего поколения и независимой реализации/описанию. Имена «LZX», «XPRESS», «CE compression» сами по себе не являются выбором декодера. Проверить наличие framing/block headers, ограничения входа/выхода и происхождение/лицензию декодера.
3. Декодировать с максимальной ожидаемой длиной 6 144 байта, запретить выход за входные границы и лишний выход. Проверить усечения, неверные длины, повреждённый поток. Ошибку декодирования сохранять как результат, не переименовывать сжатый объект в `.dll`.
4. Проверить PE: `MZ`, ограниченный `e_lfanew`, `PE\0\0`, Machine, секции и размеры, диапазоны RVA/raw, directory entries, импорты/экспорты и релокации. Фактическое значение Machine сверить с ARM CE и ROMHDR CPU; не подставлять его заранее. Сохранить локальный PE, SHA-256, отчёт валидатора и таблицы imports/exports. Независимый PE-инструмент должен прочитать тот же результат.
5. Сопоставить функции с `keybddr.dll` (TOC `0x3d07ac`, E32 VA `0x8024b0f8`, O32 VA `0x8024b164`) и историческим ASIC3 keyboard driver. Отдельно восстановить регистрируемые CE-экспорты, логические клавиши/модификаторы, язык и аппаратный транспорт. Имя `QwertyKey.dll` ещё не доказывает, что DLL сканирует матрицу.

**Артефакт завершения:** локальный проверяемый PE + таблицы + хеши + входные смещения + инструкция повторения; либо конкретный формат/недостающий фрагмент, препятствующий извлечению. Сейчас блокер — отсутствие входных байтов, поэтому PE и отчёт по машинным функциям не создавались.

## Проверенные первичные исходники для продолжения

**Подтверждено исходным кодом проекта PXADroid**, без запуска на этом экземпляре: официальный репозиторий `https://git.code.sf.net/p/pxadroid/pxakernel`, commit **`3712fd6f197113f19959eba85b3628b202e30d64`**. Далее `K:path:line` относится только к этому commit. [Дерево исходников](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/), [board file](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/blueangel.c).

`blueangel.c` содержит работающие определения и одновременно закомментированные участки/неуверенные комментарии. Код Linux даёт проверяемые кандидаты и алгоритмы для анализа, но не подтверждает разводку/ревизию единственного КПК и не становится собственным BSP автоматически. Числа Linux GPIO/IRQ могут включать программные базы; их нельзя копировать как аппаратный номер IRQ. Исходники GPL; код драйверов в Crosshair из них не переносился.

## Таблица исследовательских задач

Ниже имена выходных файлов — требуемые будущие артефакты, не утверждение об их наличии. Смещения ROM — файловые offsets декодированного `nk.nba` **с 128-байтовым заголовком**. Значения физических регистров и электрические параметры, не подтверждённые отдельным источником, остаются неизвестными.

| Приоритет / подсистема | Подтверждённая отправная точка и источник | Что установить до драйвера | Конкретный будущий артефакт / проверка | Неизвестно / блокер |
|---|---|---|---|---|
| **M1 / QWERTY** | ROM: `QwertyKey.dll` и `keybddr.dll`, offsets выше. `K:arch/arm/mach-pxa/blueangel.c:905–1021`: ASIC3 SPI, таблица клавиш. `K:drivers/input/keyboard/htc-asic-kbd.c`: разбор press/release/Fn. | Связь двух CE-компонентов; настоящий протокол контроллера, IRQ и debounce/repeat; русская раскладка отдельно от scan codes. | `qwerty_pe_report.json`, `qwerty_imports.csv`, `qwerty_scancodes.csv`, тест декодирования записанной последовательности press/release/Fn/Shift без устройства. | Исходная ROM отсутствует. На аппарате scan codes, русская раскладка и работа Fn не измерены. |
| M3 / LCD + framebuffer | ROM: `ace_ddi.dll` TOC `0x3d0980`, сжатые данные `0x2c5870`, 153 463 байта; кандидат, роль по коду не проверена. `FrontLight.dll` TOC `0x8b936c`. `K:arch/arm/mach-pxa/blueangel.c:315–508,1097–1100` и `K:drivers/video/w100fb.c`. | ATI Imageon W3200 aperture, framebuffer offset/stride/format, rotation, clock/power order и состояние от WM. Выбор панели зависит от board ID: исходник выбирает Sony для 5, Toppoly иначе; это не определение панели владельца. | `lcd_register_provenance.csv` (PA/offset/width/source), `lcd_panel_variants.md`, `framebuffer_contract.md`, локальный тест вычисления адресов/границ 240×320. | Board ID, панель, активный режим и адрес framebuffer этого экземпляра неизвестны. Значения из CE ещё не извлечены. |
| M3 / сенсор и передние кнопки | ROM: `touch.dll` TOC `0x3d07cc`, E32 VA `0x8024b1c4`, O32 VA `0x8024b230`. `K:arch/arm/mach-pxa/blueangel.c:843–902`: TSC2200 через SSP2. `K:drivers/spi/tsc2X0X-core.c`, `drivers/input/touchscreen/tsc2X0X_ts.c`, `drivers/input/keyboard/tsc2X0X_kp.c`. | Формат SPI-команд/данных, pen IRQ и общий IRQ кнопок, ориентация ADC, фильтрация, калибровочная модель, тайм-ауты и chip select. | `touch_protocol.md`, `touch_calibration_vectors.json`, unit test аффинной калибровки с границами и вырожденными точками; отдельно таблица передних кнопок. | Параметры давления/сопротивления в Linux — конфигурация старого порта, не измерения платы. Фактическая полярность/качество сигналов не проверены. |
| M2→M3 / таймер | `K:arch/arm/mach-pxa/blueangel.c:1120` выбирает `pxa_timer`; `K:arch/arm/mach-pxa/time.c`, `include/mach/regs-ost.h`. ROM: `nk.exe` TOC `0xc7e08` как цель OAL-анализа, не готовый извлечённый OAL. | Частота OS timer на PXA263, ширина counter, match/overflow, W1C semantics, доступ после handoff и влияние сна. Сверить с Intel PXA26x developer manual соответствующей ревизии. | `timer_spec.md` с точными manual chapter/page и адресами; host test переполнения/tick conversions; позже разрешённый hardware timing log. | Руководство SoC с проверенным хешем/страницами ещё не приложено. Без него не фиксировать частоту и политику сна по аналогии с другим PXA. |
| M2→M3 / IRQ и исключения | `K:arch/arm/mach-pxa/blueangel.c:1113–1122`: `pxa26x_init_irq`, `pxa25x_handle_irq`; `K:arch/arm/mach-pxa/irq.c`, `include/mach/irqs.h`, `include/mach/blueangel.h`; ASIC3 как отдельная ступень. | Вектор ARMv5, режимы/стеки exception, маски IRQ/FIQ, ack order SoC→GPIO→ASIC3, banked IRQ и wake sources. | `irq_routes.csv` с отдельными колонками physical source / GPIO / ASIC bit / Linux virtual IRQ, `exception_contract.md`, тесты маршрутизации и ограничений стека. | Linux IRQ number не равен физическому номеру. Состояние прерываний/периферии после HaRET требует отдельного подтверждения. |
| M2 / память и MMU | [HARDWARE.md](../HARDWARE.md): 128 MB сообщены WM, карта банков не измерена. `K:arch/arm/mach-pxa/pxa25x.c`, `K:arch/arm/mach-pxa/Makefile.boot`, `K:arch/arm/mach-pxa/include/mach/addr-map.h`; `K:arch/arm/include/asm/setup.h`; загрузочный контракт — [BOOT.md](../BOOT.md). | Физические банки и holes, допустимый RAM range, расположение loader/ATAG/stack/image, cache alias/DMA, таблицы страниц и будущие permissions. ROM model `0x80000000` не использовать как kernel PA. | `ram_reservations.json`, `memory_map.csv` с типами PA/VA/file offset и источниками; host test непересечения loader/kernel/stacks/ATAG. | Унаследованные mappings и RAM с пользовательским состоянием WM; допустимый аппаратный диапазон не подтверждён только размером RAM. |
| M0→M6 / питание, сон, wake | ROM: `battdrvr.dll` TOC `0x3d080c`, `battery.dll` TOC `0x3d082c`. `K:arch/arm/mach-pxa/blueangel.c:608–717,1075–1088`, `K:drivers/power/ds2760_battery.c`, `drivers/w1/slaves/w1_ds2760.c`, `arch/arm/mach-pxa/pm.c`. | Текущая PMIC/battery topology, штатные reset defaults, safe quiesce без смены зарядного режима, wake от кнопки/модема/RTC, retention RAM, backup battery. | `power_state_machine.md` и `wake_matrix.csv` с источником каждой операции; статическая сверка Linux/CE/manual, затем отдельно утверждённая измерительная процедура. | В board file sleep/wakeup настройки закомментированы; неизвестные GPIO отмечены автором вопросами. Это не готовый надёжный сценарий сна. Напряжения/токи на устройстве не измерялись. |
| M2→M5 / GSM + разговорный звук | ROM: `ril.dll` TOC `0xc7596c`, `rilgsm.dll` `0x8b9388`, `serial_cmd.dll` `0x8b93dc`, `HTC_CMD.dll` `0x8b93f8`, `wavedev.dll` `0x3d078c`. `K:arch/arm/mach-pxa/blueangel.c:786–806`: FFUART=data, DPRAM=control; `K:arch/arm/mach-pxa/htc_calypso.c`. Audio `blueangel.c:1026–1041`, `sound/soc/pxa/blueangel.c`. | Реальная граница RIL/OEM transport, DPRAM framing/handshake, wake/reset, flow control, тайм-ауты, routing UDA1380/Calypso, ответы и ошибки. | `phone_component_graph.md` по imports/call sites, `modem_transport_spec.md`, `audio_routes.csv`, parser tests на записанных/синтетических кадрах без посылки команд модему. | В старом `calypso_data` power/sleep GPIO стоят `-1` с вопросами. Исторический порт не устанавливает рабочий протокол и не доказывает звонки/SMS/сон. |
| Перед физическим M2 / диагностика | `K:arch/arm/mach-pxa/blueangel.c:92–109,248–249,786`: FFUART связан с модемом; STUART pinmux есть, но переключатель SIR/serial описан неуверенно. | Доказанная внешняя линия/электрические уровни, pinmux и конфликт с модемом; либо RAM crash log + доказанный способ его прочесть после reset без уничтожения данных. | `diagnostic_transport.md`: источник схемы, PA/width регистров, предусловия, timeout/error path и процедура разрешённого сбора. | `console=ttyS0` из Linux startup не доказывает внешний debug UART. На Crosshair Boot 0.1 используется только UART эмулятора; FFUART реального КПК для логов не трогать по догадке. |

Подтверждённые реестры по именам ещё не восстановлены: для всех CE DLL требуется связать registry `Drivers\\BuiltIn`, `Dll`, `Prefix`, `Index`, `Order`, IRQ/источники питания с фактическими exports и машинными инструкциями. Документация CE 5.0 полезна как справочник, но WM2003 SE требует проверки своей версии ABI.

## Один конкретный следующий шаг

Возобновить **M1 QwertyKey** с локального исходного EXE указанного SHA-256, выполнить полный анализ в новый приватный каталог и сохранить 2 029 исходных байт объекта с хешем. Только после этого выбирать декодер. Параллельный следующий шаг ядра — чтение/доказательство контракта Blue Angel из [BOOT.md](../BOOT.md); успешный VersatilePB не закрывает этот аппаратный этап.
