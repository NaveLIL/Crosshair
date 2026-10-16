# Целевая аппаратура Blue Angel

Целевая платформа — i-mate PDA2k / HTC Blue Angel (PH20B), Intel XScale PXA263, ARMv5TE, 400 MHz, RAM 128 MB, экран 240×320, резистивный сенсор и выдвижная QWERTY. Это паспорт целевой конфигурации, не подтверждение уже работающего BSP.

Исторический PXADroid board source закреплён commit `3712fd6f197113f19959eba85b3628b202e30d64`: [blueangel.c](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/blueangel.c), [blueangel.h](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/include/mach/blueangel.h).

| Узел | Подтверждено историческим исходником | Что неизвестно |
|---|---|---|
| Дисплей | Внешний ATI Imageon W3200, варианты панели по board ID | Конкретная ревизия, framebuffer/stride/active mode |
| Ввод | TSC2200 touch/front keys; ASIC3 SPI sliding keyboard | Полный protocol/reset/IRQ contract и русская раскладка |
| SD | ASIC3 SD resources, дочерний TMIO MMC | Полная register-level совместимость и SDIO |
| GSM | Calypso, FFUART=data, DPRAM=control | DPRAM framing/handshake, wake и разговорный audio path |
| Питание/звук | ASIC3, codec UDA1380 и отдельные power controls | Безопасная последовательность и реальный suspend/resume |

Число 128 MB не устанавливает безопасный диапазон RAM при загрузке из WM. Полная физическая топология Flash, банки/aliases памяти, DMA и резервы loader требуют проверки. ROM model VA `0x80000000` из анализатора не является адресом размещения ядра.

Заводская WM2003 может хранить пользовательское состояние в RAM; HaRET handoff не обещает возврата в ту же сессию. Физические операции требуют отдельной процедуры. [Исследование загрузки](docs/BLUEANGEL_BOOT_RESEARCH.md), [матрица эмулятора](crosshair-emulator/FEASIBILITY.md).
