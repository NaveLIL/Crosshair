# Ввод и интерфейс Crosshair

Аппаратная sliding QWERTY, передние кнопки/навигация и резистивный сенсор — полноценные способы управления. Основные приложения должны работать с клавиатуры; доступность этих функций на новом BSP пока не подтверждена.

Разделяются controller scan codes, key up/down/repeat, Fn/Shift modifiers, логическая раскладка (включая кириллицу), текстовый ввод и язык UI. Легенды на клавишах не доказывают software mapping. Исторические источники указывают ASIC3 SPI keyboard и TSC2200 touch/front-key paths: [исследование](docs/RESEARCH_NEXT.md).

Для сенсора нужен воспроизводимый calibration transform с проверкой corners, границ и вырожденных точек. Калибровка в начале первого запуска — проектное направление. Формат ADC, давление, фильтрация и IRQ ещё исследуются.

Целевой экран 240×320 требует компактного UI, ясного focus, прямого управления и читаемой кириллицы. Ни GUI, ни аппаратные input drivers в Boot0.1 не реализованы.

UI0.1 добавляет [отдельный software primitive layer](docs/UI_0.1.md):240×320 RGB565, bitmap кириллица, clipped drawing, bounded dirty regions и host framebuffer export. UI0.2 поверх него реализует [компоненты, видимый focus, логические действия и FIFO](docs/UI_0.2.md), выбор/прокрутку тестового каталога «Приложения» и кириллический фильтр. Это host-tested экран и ARM compile-only library. Stylus calibration, физическая QWERTY, повтор/дребезг и ATI display transport остаются отдельными контрактами. GPIO test wires эмулятора не выдаются за контроллер аппаратной клавиатуры.
