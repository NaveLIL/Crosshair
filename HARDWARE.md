# Целевая аппаратура Blue Angel

Целевая платформа — i-mate PDA2k / HTC Blue Angel (PH20B), Intel XScale PXA263, ARMv5TE, 400 MHz, RAM 128 MB, экран 240×320, резистивный сенсор и выдвижная QWERTY. Это паспорт целевой конфигурации, не подтверждение уже работающего BSP.

Исторический PXADroid board source закреплён commit `3712fd6f197113f19959eba85b3628b202e30d64`: [blueangel.c](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/blueangel.c), [blueangel.h](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/arch/arm/mach-pxa/include/mach/blueangel.h).

| Узел | Подтверждено историческим источником | Что неизвестно |
|---|---|---|
| Дисплей | Внешний ATI Imageon W3200, варианты панели по board ID | Конкретная ревизия, framebuffer/stride/active mode |
| Ввод | TSC2200 touch/front keys; ASIC3 SPI sliding keyboard | Полный protocol/reset/IRQ contract и русская раскладка |
| SD | ASIC3 SD resources, дочерний TMIO MMC | Полная register-level совместимость и SDIO |
| GSM | Calypso, FFUART=data, DPRAM=control | DPRAM framing/handshake, wake и разговорный audio path |
| Питание/звук | ASIC3, codec UDA1380 и отдельные power controls | Безопасная последовательность и реальный suspend/resume |
| Задняя VGA-камера | Отдельный color CMOS camera module; задний объектив и режим фото 640×480 в руководстве Blue Angel/Qtek 9090, см. источник ниже | Модель сенсора, data/control interface, адреса регистров, clocks/reset, GPIO/IRQ/DMA и последовательность питания |

**Источник, без проверки данного экземпляра:** оригинальное *Pocket PC Phone User Manual* для Blue Angel/Qtek 9090 (публичное зеркало PDF): [с.9, back view и Camera Lens](https://altehandys.de/downloads/man-qtek-9090.pdf#page=9), [с.129, photo capture 640×480](https://altehandys.de/downloads/man-qtek-9090.pdf#page=129), [с.162, Camera Module](https://altehandys.de/downloads/man-qtek-9090.pdf#page=162). Это паспорт камеры, не register-level contract; перечисленные неизвестные не заполнены по аналогии с другим HTC. Направление исследования — OEM camera-компоненты из статической ROM-инвентаризации, исторические board/driver sources и документация конкретного сенсора после его идентификации. Драйвер Crosshair и аппаратное испытание камеры отсутствуют.

Число 128 MB не устанавливает безопасный диапазон RAM при загрузке из WM. Полная физическая топология Flash, банки/aliases памяти, DMA и резервы loader требуют проверки. ROM model VA `0x80000000` из анализатора не является адресом размещения ядра.

Заводская WM2003 может хранить пользовательское состояние в RAM; HaRET handoff не обещает возврата в ту же сессию. Физические операции требуют отдельной процедуры. [Исследование загрузки](docs/BLUEANGEL_BOOT_RESEARCH.md), [матрица эмулятора](crosshair-emulator/FEASIBILITY.md).
