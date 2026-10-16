# Статический анализ Blue Angel

Приоритет **M1 QwertyKey.dll** остаётся отдельной задачей. Сохранённая историческая инвентаризация известного пакета содержит 14 ROMHDR regions, 306 module entries и 662 file entries; это не число готовых драйверов и не полная карта физического устройства.

[Исходный отчёт](research/initial_static_report.md), [package hashes](research/package_report.json), [TOC](research/rom_inventory.json). Текущий полный EXE→CAB→NBF rerun не выполнен: исходный EXE/NBA отсутствует. Проверены 19 синтетических parser tests, включая CAB backend, повреждённые данные и все 1024 усечённых префикса fixture.

QwertyKey: TOC file offset `0x8b92e0`, compressed data offset `0x634974`, stored length 2029, expected uncompressed size 6144. Все offsets относятся к декодированному nk.nba с 128-byte header; это не kernel PA. Кодек пока не установлен, пригодный PE не получен.

Следующий результат: сверенный локальный input → exact compressed bytes/hash → доказанный decoder с bounds/error tests → проверяемый PE + Machine/sections/imports/exports/hash. Не выдавать сжатый объект за DLL и имена компонентов за установленный аппаратный протокол. [Подробный план и источники](docs/RESEARCH_NEXT.md).
