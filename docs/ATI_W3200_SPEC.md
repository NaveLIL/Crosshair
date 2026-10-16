# ATI Imageon W3200: исторический контракт Blue Angel

Engineering Wave004, 16.10.2026. **Результат — исследование первоисточников, не готовый драйвер и не аппаратная проверка.** Ни MMIO, ни запуск программ на PDA2k не выполнялись. Полное vendor programming manual именно W3200 в проверенных материалах не установлено; ниже зафиксировано поведение исторического Linux-драйвера. [Синтетический display-test Wave004](../crosshair-emulator/README.md) проверяет отдельный контракт Crosshair и **не моделирует ATI W3200**.

Статусы: **источник** — закреплённый код; **вывод** — вычисление/интерпретация этого кода; **неизвестно** — свойство экземпляра или silicon contract, не доказанное источником. ELF/UI tests не превращают эти сведения в аппаратное подтверждение.

## Источники и границы семейства

- **K:** PXADroid Linux commit [`3712fd6f197113f19959eba85b3628b202e30d64`](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/). Прочитаны machine file, два machine headers, `drivers/video/w100fb.c`, его private header и `include/video/w100fb.h` через `git show`. Это конкретная историческая редакция, не утверждение о последней или единственно правильной реализации.
- **H:** HaRET commit [`d585ee6ad903e0e6ad1dc943a3157e86db43ddf7`](https://github.com/KevinOConnor/haret/tree/d585ee6ad903e0e6ad1dc943a3157e86db43ddf7), `src/video.cpp`.
- [Манифест](../research/w3200-sources.json) закрепляет commit, path, git blob SHA-1, SHA-256 и длину девяти файлов, включая upstream `COPYING`. Код Linux/HaRET здесь не скопирован и не перелицензирован в MIT. Документ содержит факты и анализ; лицензии будущего переноса реализации требуют отдельного рассмотрения.

**Источник:** [K blueangel.c315–317,496–507][board] называет соединение Sony/Toppoly с Imageon **w3200**, но регистрирует платформенный драйвер **w100fb**. [K w100fb.h250–252][ids] различает `W100=0x57411002`, `W3200=0x56441002`, `W3220=0x57441002`; [driver1668–1679][graphic] использует отдельную ветку `f_w32xx`, отличную от W100. Имя файла `w100fb` не доказывает тождество чипов или пригодность произвольного W100 datasheet. Реальный CHIP_ID/revision экземпляра **неизвестен**.

## Адреса и память

Все PA ниже — **CPU physical addresses**, производные от исторической карты Blue Angel; границы end exclusive. [K blueangel.h24][ba-header] задаёт ATI на `PXA_CS2_PHYS`, [addr-map.h9][addr-map] даёт `0x08000000`; machine resource имеет размер `SZ_16M`. [K w100fb.h237–245][windows] и [probe824–894][probe] задают окна:

| Область | PA / длина | Статус и смысл |
|---|---|---|
| Ресурс ATI CS2 | `[0x08000000,0x09000000)`, 16 MiB | **Источник.** Адресное пространство устройства, не объём VRAM |
| Configuration aperture | `0x08000000`, `0x10` байт | **Источник.** `cfgREG_BASE=4`, `cfgINTF_CNTL=5`, `cfgSTATUS=6`, `cfgCPU_DEFAULTS=7`; access/reset ambiguity ниже |
| Register aperture | `0x08010000`, `0x2000` байт | **Источник.** Driver mapping; `REG_BASE=0x10000` внутри пространства ATI |
| CPU memory aperture | `[0x08100000,0x09000000)`, 15 MiB | **Источник.** `MEM_WINDOW_BASE=0x100000`, length=`0xf00000`; это окно, не capacity |
| Внутренняя память ATI | `MEM_INT_SIZE+1=0x60000`, 384 KiB | **Источник.** Перемещаемая; nominal chip offset=`0x200000` не является постоянным адресом активного framebuffer |
| Внешняя память board data | `.size+1=0x400000`, 4 MiB | **Источник/вывод.** `.size=0x3fffff` — максимальное смещение. Фактическая комплектация/исправность не измерены |
| Framebuffer обычного режима driver | PA=`0x08800000`; видимые данные `[0x08800000,0x08825800)` | **Вывод** для 240×320×2=153600 байт после выполнения mapping/mode path; не адрес, измеренный в WM |

Последняя строка требует существенного уточнения: [set_par703–708][format] выбирает внутреннюю память, когда кадр помещается в 384 KiB. По умолчанию `extmem_never_off=0` ([probe866][probe]); [setup_memory1556–1568][memory] отключает external memory и переносит internal memory на **chip offset `0x800000`**. Поэтому QVGA framebuffer по PA `0x08800000` здесь опирается на **internal**, а не автоматически на external 4 MiB. При других режимах/sysfs-состоянии mapping меняется. `REMAPPED_FB_LEN=0x15ffff` в driver81/886 — отдельное software поле `screen_size`, не доказательство физического размера VRAM.

**Источник:** [check_var659–670 и set_par700][format] задают 16 bpp, RGB565: R bits15..11, G10..5, B4..0, alpha отсутствует. [set_dispregs1689–1690][graphic] задаёт graphic offset=`0x800000` при normal orientation и pitch=`xres*2`, то есть **480 bytes/row**. Для 90°/270° меняются offset/orientation и xres/pitch. **Неизвестно:** действующие WM pitch, orientation, CIF byte swapping, bus endianness и активное отображение памяти после HaRET handoff. Packed RGB565 в Linux не доказывает возможность сразу передать текущий UI byte buffer без проверки этих условий.

## Регистры, необходимые следующему исследованию

**Источник:** [K private header24–115][registers], [175–198][memory-regs], [216–223][clock-regs]. `r` ниже — offset **в register aperture**, поэтому PA=`0x08010000+r`; это не offset от framebuffer. Driver использует `readl/writel` для этих регистров, а не uniform byte access.

| Группа | Offsets `r` / назначение |
|---|---|
| Identity / interrupt | `0000 CHIP_ID`, `0004 REVISION_ID`, `0200 GEN_INT_CNTL`, `0204 GEN_INT_STATUS` |
| Framebuffer | `0410 LCD_FORMAT`, `0414 GRAPHIC_CTRL`, `0418 GRAPHIC_OFFSET`, `041c GRAPHIC_PITCH` |
| Геометрия | `0420 CRTC_TOTAL`, `0424 ACTIVE_H_DISP`, `0428 ACTIVE_V_DISP`, `042c GRAPHIC_H_DISP`, `0430 GRAPHIC_V_DISP` |
| Panel timings | `048c SS`, `0490 LS`, `0494 REV`, `049c DCLK`, `04a0 GS`, `04a4 VPOS_GS`, `04a8 GCLK`, `04ac GOE` |
| Panel/data update | `04c4 LCDD_CNTL1`, `04c8 LCDD_CNTL2`, `04cc GENLCD_CNTL1`, `04d0 GENLCD_CNTL2`, `0524 GENLCD_CNTL3`, `04d8 DISP_DB_BUF_CNTL`, `0538 DISP_DEBUG2` |
| Memory | `0188 MC_FB_LOCATION`, `0190 MC_EXT_MEM_LOCATION`, `018c MEM_EXT_CNTL`, `0194 MEM_EXT_TIMING_CNTL`, `0198 MEM_SDRAM_MODE_REG`, `019c MEM_IO_CNTL`, `01a4 MC_BIST_CTRL` |
| Clock/power | `0080 CLK_PIN_CNTL`, `0084 PLL_REF_FB_DIV`, `0088 PLL_CNTL`, `008c SCLK_CNTL`, `0090 PCLK_CNTL`, `0094 CLK_TEST_CNTL`, `0098 PWRMGT_CNTL`, `009c PWRMGT_STATUS` |
| ATI GPIO | `04b8 DATA1`, `04bc CNTL1`, `04c0 CNTL2`, `0528 DATA2`, `052c CNTL3`, `0530 CNTL4` |

Например, GRAPHIC_PITCH PA=`0x0801041c`, но framebuffer PA=`0x08800000`. Значения `W100_FB_BASE` и `GRAPHIC_OFFSET` — **адреса внутри ATI**, не PXA RAM PA. ATI GPIO также нельзя смешивать с GPIO PXA или ASIC3. Полный register access policy (RO/WO/W1C/reserved bits/reset values) этим перечнем **не установлен**.

## Панель и последовательности в редакции K

**Источник:** [board1097–1100][panel-select] выбирает для **boardid5 Sony ACX502BMV**, для остальных — **Toppoly TD035STEC1**. Board ID собирается из PXA GPIO66/67/76, [341–350][board-id]. Реальный вариант владельца **неизвестен**; внешний вид устройства и строка модели его не устанавливают.

| Параметры board data | Sony / mode5 | Toppoly / mode6 |
|---|---|---|
| x/y; margins left,right,upper,lower | 240/320; `0,31,15,0` | 240/320; `20,19,3,2` |
| CRTC_SS / LS | `80150014 / a0fb00f7` | `80150014 / a0020110` |
| CRTC_GS / VPOS_GS | `c0080007 / c0080007` | `c0890088 / 01450144` |
| REV / DCLK / GCLK / GOE | `0000000a / 81700030 / 8015010f / 0` | `0000000a / a1700030 / 8015010f / 0` |
| PLL MHz / pixel divider field normal,rotated | `80 / 15,15` | `80 / 14,14` |

Источник таблицы — [board409–457][modes]. Оба режима задают PLL как источник pixel/sys clock, sys divider field0; crystal board data=`16 MHz` ([486–493][board]). Число в divider field не следует без формулы выдавать за прямой коэффициент. В [16MHz PLL table1191][pll] параметры строки80MHz=`M1,N_int9,N_fac0,tfgoal e0,lock_time13`, причём автор прямо пометил **tfgoal guessed**. Частота кадров/допуски панели на экземпляре не измерены.

Исторический порядок, **не процедура безопасного включения реального PDA**:

1. [hw_init1055–1147][hw-init]: soft reset; scratch/CIF configuration; cfg interface/CPU defaults; cfgREG_BASE=`1`; wrap buffers/RBBM; выбор565 через DISP_DEBUG2; начальные **ATI** GPIO DATA1/2=`0/0`, direction1/2=`e0000000/0`, output-enable1/2=`003c2000/0` из [board477–483][board]. Начальное состояние chip-select timing/WM handoff здесь не доказано.
2. [activate_var585–599][activate]: `pwm_setup → setup_memory → init_clocks → clear_screen → vsync → update_disable → init_lcd → set_dispregs → update_enable → init_graphic_engine`. Здесь `pwm_setup` настраивает **ATI power management/clocks**, не доказанный brightness PWM подсветки. Детали clock setup — [1389–1479][clock-setup], PLL calibration — [1338–1371][pll-set].
3. [init_lcd1493–1545][lcd-init]: active/total geometry и panel timings, затем common board values `LCD_FORMAT=00000003`, `LCDD1=0`, `LCDD2=0003ffff`, `GENLCD1=00fff003`, `GENLCD2=00000003`, `GENLCD3=000102aa`; counters0/background`ff00`, DISP_DEBUG2 overlay hack. `GRAPHIC_CTRL` сначала обнуляется, затем выбираются именно поля W32xx; их расположение отличается от W100 ([header526–540][graphic-fields]).
4. **Только external-memory branch** [1584–1601][memory]: BIST=`7800`, EXT_CNTL=`01040010`; SDRAM_MODE последовательно `00200021`, `80200021`, `00250000` с `udelay(100)` после каждого; TIMING=`00001545`, IO=`7ddd7333`. Затем семь BM values из [board467–474][board]. Обычный internal QVGA path этого branch не исполняет. Чужие timing constants не являются замером/электрической спецификацией.
5. Отдельный panel power callback [board321–337][board]: последовательно ASIC3 B3/B4/B5=`power`; для boardid4/5 также B2, для6 — C14/C15. В этом callback **нет explicit delays**. Suspend/resume вызывают blank/unblank ([385–397][board]). Напряжения, допустимые задержки, зависимости rail/clock/reset и безопасный cold start **неизвестны**. Название отдельного ASIC3 B6 `FL_PWR_ON` не устанавливает brightness/power contract подсветки.

[vsync1773–1810][vsync] исторически **polls** GEN_INT_STATUS bit1 с bounded timeout30000 и `udelay(1)`, временно управляя GEN_INT_CNTL bit1 и очищая status. Machine resource не содержит IRQ. Это источник для poll algorithm, но не подтверждение ATI→PXA IRQ wiring, точной частоты vblank или completion semantics для нашего present callback.

## Неоднозначности и следующий аппаратный контракт

| Факт / пробел | Что требуется перед реальным backend |
|---|---|
| **Источник, неоднозначность reset access:** `cfgSTATUS=6`, но [soft_reset1001–1005][reset] использует `(u16 *)base + cfgSTATUS`, т.е. CPU byte offset **12**, с 16-bit read/write и двумя100µs delays | Найти W3200 interface specification/независимую верифицированную реализацию; не исправлять автоматически на byte6 и не объявлять byte12 vendor contract |
| **Источник:** [update_disable/enable1010–1027][reset] не инициализирует целиком union перед записью, а header575–597 оставляет reserved upper bits | Установить допустимые write masks/reset values; не копировать неопределённые C bits в Rust |
| **Источник с гипотезой автора:** external unmap value «probably irrelevant» ([1564][memory]); PLL tfgoal «guessed» | Нужен vendor contract либо отдельный проверяемый эксперимент; не считать комментарии измерением |
| **Неизвестно:** активный WM framebuffer PA/stride/format/rotation и состояние после HaRET | Сначала спроектировать отдельно разрешаемое получение metadata. [H video.cpp24–32,67–117][h-video] объявляет stride/format поля API, но сохраняет лишь width/height/pointer; `VRAM` PA сам по себе **не доказывает pitch** |
| **Неизвестно:** CHIP_ID/revision, boardid/panel, CS2 timing, reset/power state экземпляра | Согласованная ограниченная процедура наблюдения; адресная таблица исходника не разрешает MMIO probe |
| **Неизвестно:** memory ordering/cache attributes, write completion, scanout/dirty update tearing | Определить CPU mapping/barriers и момент завершения `present`; QEMU cache NOP и host renderer не проверяют silicon coherence |
| **Неизвестно:** cold-init, rail delays, backlight, suspend/resume/recovery | Получить точную схему/панельную документацию и независимые источники; callback Linux недостаточен для безопасной аппаратной последовательности |

Следующий конкретный шаг: оформить **read-only metadata handoff** как отдельный проектируемый контракт (chip/panel identity, framebuffer PA, width/height, signed x/y stride, format, orientation, accessible bounds, retained state). На текущем этапе его можно проверить fixture-тестами без устройства. Перед запуском на PDA необходима отдельная авторизация владельца и проверенная процедура; synthetic display-test остаётся самостоятельным backend и не является реализацией перечисленных ATI registers.

[board]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/blueangel.c#l315
[ba-header]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/include/mach/blueangel.h#l21
[addr-map]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/include/mach/addr-map.h#l9
[windows]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.h#l237
[ids]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.h#l250
[probe]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l811
[format]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l643
[graphic]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l1606
[registers]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.h#l24
[memory-regs]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.h#l175
[clock-regs]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.h#l216
[panel-select]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/blueangel.c#l1097
[board-id]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/blueangel.c#l341
[modes]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/blueangel.c#l409
[pll]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l1187
[hw-init]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l1055
[activate]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l581
[clock-setup]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l1389
[pll-set]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l1338
[lcd-init]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l1482
[graphic-fields]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.h#l526
[memory]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l1549
[vsync]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l1773
[reset]: https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/video/w100fb.c#l999
[h-video]: https://github.com/KevinOConnor/haret/blob/d585ee6ad903e0e6ad1dc943a3157e86db43ddf7/src/video.cpp#L24
