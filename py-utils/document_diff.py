import re
from dataclasses import dataclass
from typing import List, Set, Dict, Optional

@dataclass
class HeaderInfo:
    line_idx: int
    level: int
    is_new_section: bool

@dataclass
class TableInfo:
    header_idx: int
    sep_idx: int
    start_body_idx: int
    end_body_idx: int


class MarkdownDocumentParser:
    """Отвечает за разметку структуры документа: заголовков, таблиц и границ разделов."""
    
    def __init__(self, lines: List[str]):
        self.lines = lines
        self.num_lines = len(lines)
        self.headers: Dict[int, HeaderInfo] = {}
        self.tables: List[TableInfo] = []
        self.line_to_table: Dict[int, TableInfo] = {}
        # Для каждой строки храним (start_idx, end_idx) её текущего раздела (между заголовками)
        self.section_bounds: List[tuple[int, int]] = [(0, self.num_lines - 1)] * self.num_lines
        # Цепочка родительских заголовков для каждой строки
        self.line_ancestors: List[List[int]] = [[] for _ in range(self.num_lines)]

    @staticmethod
    def is_table_row(line: str) -> bool:
        s = line.strip()
        return s.startswith('|') and s.endswith('|') and len(s) > 2

    @staticmethod
    def is_table_separator(line: str) -> bool:
        s = line.strip()
        return MarkdownDocumentParser.is_table_row(s) and bool(re.match(r'^\|[\s\-:|]+\|$', s))

    def parse(self):
        self._parse_headers_and_sections()
        self._parse_tables()

    def _parse_headers_and_sections(self):
        header_indices = []
        stack: List[HeaderInfo] = []

        for idx, line in enumerate(self.lines):
            match = re.match(r'^(#{1,6})\s+(.*)', line)
            if match:
                level = len(match.group(1))
                is_new = ('[ticket]' in line) and ('[/ticket]' not in line)
                h_info = HeaderInfo(line_idx=idx, level=level, is_new_section=is_new)
                self.headers[idx] = h_info
                header_indices.append(idx)

                while stack and stack[-1].level >= level:
                    stack.pop()
                stack.append(h_info)

            # Сохраняем активную иерархию заголовков для текущей строки
            self.line_ancestors[idx] = [h.line_idx for h in stack]

        # Вычисляем строгие границы контента внутри каждого заголовка (до следующего заголовка)
        boundaries = [0] + header_indices + [self.num_lines]
        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            # Контент раздела начинается со строки ПОСЛЕ заголовка (если это не 0-я строка без заголовка)
            content_start = start + 1 if start in self.headers else start
            content_end = boundaries[i + 1] - 1
            for line_idx in range(start, boundaries[i + 1]):
                self.section_bounds[line_idx] = (content_start, content_end)

    def _parse_tables(self):
        i = 0
        while i < self.num_lines:
            if (i + 1 < self.num_lines 
                and self.is_table_row(self.lines[i]) 
                and self.is_table_separator(self.lines[i + 1])):
                
                header_idx = i
                sep_idx = i + 1
                body_start = i + 2
                body_end = body_start - 1

                # Ищем конец таблицы (пока идут строки таблицы и не начался новый заголовок)
                j = body_start
                while j < self.num_lines and self.is_table_row(self.lines[j]) and j not in self.headers:
                    body_end = j
                    j += 1

                if body_end >= body_start:
                    t_info = TableInfo(header_idx, sep_idx, body_start, body_end)
                    self.tables.append(t_info)
                    for row_idx in range(header_idx, body_end + 1):
                        self.line_to_table[row_idx] = t_info
                i = j
            else:
                i += 1


class DiffContextExtractor:
    """Извлекает индексы строк с правками, расширяет контекст и собирает итоговый документ."""

    def __init__(self, doc: MarkdownDocumentParser, context_lines: int = 2):
        self.doc = doc
        self.context_lines = context_lines
        self.selected_indices: Set[int] = set()

    def extract(self) -> str:
        core_diff_indices = self._find_core_diffs()
        self._expand_context(core_diff_indices)
        self._attach_structural_elements()
        return self._render()

    def _find_core_diffs(self) -> Set[int]:
        """Находит базовые номера строк с тегами [ticket] и целые новые разделы."""
        core_indices: Set[int] = set()
        in_ticket_block = False
        new_section_level: Optional[int] = None

        for idx, line in enumerate(self.doc.lines):
            # 1. Проверка начала/конца нового раздела (тег в хедере без закрывающего)
            if idx in self.doc.headers and not in_ticket_block:
                h_info = self.doc.headers[idx]
                if new_section_level is not None and h_info.level <= new_section_level:
                    new_section_level = None
                
                if h_info.is_new_section:
                    new_section_level = h_info.level

            if new_section_level is not None:
                core_indices.add(idx)
                continue

            # 2. Поиск обычных однострочных и многострочных тегов [ticket]
            if '[ticket]' in line or in_ticket_block:
                core_indices.add(idx)
                open_cnt = line.count('[ticket]')
                close_cnt = line.count('[/ticket]')
                if open_cnt > close_cnt:
                    in_ticket_block = True
                elif close_cnt > open_cnt or (in_ticket_block and close_cnt > 0):
                    in_ticket_block = False

        return core_indices

    def _expand_context(self, core_indices: Set[int]):
        """Расширяет каждую найденную строку на +-N строк с обрезкой по границам блока."""
        self.selected_indices.update(core_indices)

        for idx in core_indices:
            # Не расширяем контекст для самих строк-заголовков
            if idx in self.doc.headers:
                continue

            # Определяем жёсткие границы (min_bound, max_bound) для текущей строки
            if idx in self.doc.line_to_table:
                table = self.doc.line_to_table[idx]
                min_bound, max_bound = table.start_body_idx, table.end_body_idx
            else:
                min_bound, max_bound = self.doc.section_bounds[idx]

            # Шагаем вверх и вниз, но не выходим за пределы min_bound / max_bound
            start_ctx = max(min_bound, idx - self.context_lines)
            end_ctx = min(max_bound, idx + self.context_lines)

            for ctx_idx in range(start_ctx, end_ctx + 1):
                # Если мы в обычном тексте, не захватываем случайные строки чужих таблиц сверху/снизу
                if idx not in self.doc.line_to_table and ctx_idx in self.doc.line_to_table:
                    continue
                self.selected_indices.add(ctx_idx)

    def _attach_structural_elements(self):
        """Добавляет родительские заголовки и шапки таблиц для всех выбранных строк."""
        extra_indices: Set[int] = set()

        for idx in self.selected_indices:
            # Добавляем все родительские заголовки раздела
            extra_indices.update(self.doc.line_ancestors[idx])

            # Если строка принадлежит таблице — добавляем её шапку и разделитель
            if idx in self.doc.line_to_table:
                table = self.doc.line_to_table[idx]
                extra_indices.add(table.header_idx)
                extra_indices.add(table.sep_idx)

        self.selected_indices.update(extra_indices)

    def _render(self) -> str:
        """Собирает итоговый текст по отсортированным номерам строк."""
        if not self.selected_indices:
            return ""

        sorted_indices = sorted(self.selected_indices)
        result_lines: List[str] = []
        prev_idx: Optional[int] = None

        for idx in sorted_indices:
            # Если между соседними выбранными строками был вырезан кусок текста,
            # можно визуально отделить их пустой строкой (кроме строк внутри одной таблицы)
            if prev_idx is not None and idx - prev_idx > 1:
                is_same_table = (
                    idx in self.doc.line_to_table 
                    and prev_idx in self.doc.line_to_table 
                    and self.doc.line_to_table[idx] == self.doc.line_to_table[prev_idx]
                )
                if not is_same_table and result_lines and result_lines[-1] != '':
                    result_lines.append('')

            # Добавляем пустую строку перед заголовками для чистого Markdown
            if idx in self.doc.headers and result_lines and result_lines[-1] != '':
                result_lines.append('')

            result_lines.append(self.doc.lines[idx])
            prev_idx = idx

        # Чистим тройные переносы строк
        return re.sub(r'\n{3,}', '\n\n', '\n'.join(result_lines)).strip() + '\n'


if __name__ == '__main__':
    INPUT_FILE = 'documentation.md'
    OUTPUT_FILE = 'compact_changes.md'
    CONTEXT_RADIUS = 2  # Сколько строк до и после правки захватывать (+- N)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        raw_lines = f.read().splitlines()

    parser = MarkdownDocumentParser(raw_lines)
    parser.parse()

    extractor = DiffContextExtractor(parser, context_lines=CONTEXT_RADIUS)
    compact_markdown = extractor.extract()

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as out:
        out.write(compact_markdown)

    print(f"Готово! Сохранено строк: {len(extractor.selected_indices)} из {len(raw_lines)}.")
