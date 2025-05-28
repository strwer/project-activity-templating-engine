import re
import os
from datetime import datetime
from collections import defaultdict


class TemplateError(Exception):
    """Базовый класс ошибок шаблонизатора"""
    pass


class TemplateNotFoundError(TemplateError):
    """Ошибка при отсутствии файла шаблона"""
    pass


class TemplateSyntaxError(TemplateError):
    """Ошибка синтаксиса в шаблоне"""
    pass


class TemplateEngine:
    def __init__(self, template_dir=None):
        self.template_dir = template_dir
        self.filters = self._get_default_filters()
        self.tags = self._get_default_tags()
        self.templates = {}  # Кэш загруженных шаблонов

    def _get_default_filters(self):
        """Стандартные фильтры"""
        return {
            'upper': str.upper,
            'lower': str.lower,
            'capitalize': str.capitalize,
            'escape': lambda x: str(x).replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'),
            'default': lambda x, y='': x if x else y
        }

    def _get_default_tags(self):
        """Стандартные теги"""
        return {
            'now': self._tag_now,
            'include': self._tag_include,
            'block': self._tag_block,
            'extends': self._tag_extends
        }

    def add_filter(self, name, func):
        """Добавление пользовательского фильтра"""
        self.filters[name] = func

    def add_tag(self, name, func):
        """Добавление пользовательского тега"""
        self.tags[name] = func

    def render(self, template_content: str, context: dict = None) -> str:
        """Рендеринг шаблона из строки"""
        context = context or {}
        blocks = {}

        if '{% extends ' in template_content:
            return self._render_with_inheritance(template_content, context)

        output = []
        tokens = self._parse_template(template_content)
        i = 0
        n = len(tokens)

        while i < n:
            token_type, token_value = tokens[i]

            if token_type == 'TEXT':
                output.append(token_value)
                i += 1
            elif token_type == 'VAR':
                output.append(self._resolve_variable(token_value, context))
                i += 1
            elif token_type == 'BLOCK':
                i = self._process_block(tokens, i, context, output, blocks)

        return ''.join(output)

    def render_template(self, template_name: str, context: dict = None) -> str:
        """Рендеринг шаблона из файла"""
        template_content = self.load_template(template_name)
        return self.render(template_content, context or {})

    def load_template(self, template_name: str) -> str:
        """Загрузка шаблона из файла"""
        if template_name not in self.templates:
            path = os.path.join(self.template_dir, template_name) if self.template_dir else template_name
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.templates[template_name] = f.read()
            except FileNotFoundError:
                raise TemplateNotFoundError(f"Template '{template_name}' not found")
            except UnicodeDecodeError:
                raise TemplateError(f"Encoding error in template '{template_name}'")
        return self.templates[template_name]

    def _parse_template(self, template: str) -> list:
        """Разбор шаблона на токены"""
        tokens = []
        pattern = re.compile(
            r'(?P<var>\{\{\s*(.*?)\s*\}\})|'
            r'(?P<block>\{\%\s*(.*?)\s*\%\})|'
            r'(?P<text>[^\{\}]+)'
        )
        for match in pattern.finditer(template):
            if match.group('var'):
                tokens.append(('VAR', match.group(2).strip()))
            elif match.group('block'):
                tokens.append(('BLOCK', match.group(4).strip()))
            elif match.group('text'):
                tokens.append(('TEXT', match.group('text')))
        return tokens

    def _resolve_variable(self, var_path: str, context: dict) -> str:
        """Обработка переменной с фильтрами"""
        if '|' in var_path:
            var_name, *filters = [p.strip() for p in var_path.split('|')]
            value = self._get_variable_value(var_name, context)
            return self._apply_filters(value, filters)
        return str(self._get_variable_value(var_path, context))

    def _get_variable_value(self, var_path: str, context: dict):
        """Получение значения переменной из контекста"""
        parts = var_path.split('.')
        value = context

        try:
            for part in parts:
                if isinstance(value, dict):
                    value = value[part]
                elif hasattr(value, part):
                    value = getattr(value, part)
                else:
                    return ''
            return value if value is not None else ''
        except (KeyError, AttributeError):
            return ''

    def _apply_filters(self, value, filters: list) -> str:
        """Применение фильтров к значению"""
        for filter_name in filters:
            if ':' in filter_name:
                filter_name, *args = filter_name.split(':')
                if filter_name in self.filters:
                    value = self.filters[filter_name](value, *args)
            elif filter_name in self.filters:
                value = self.filters[filter_name](value)
        return str(value)

    def _process_block(self, tokens, index, context, output, blocks):
        """Обработка тегов шаблона"""
        token_type, token_value = tokens[index]
        parts = token_value.split(maxsplit=1)
        tag_name = parts[0] if parts else ''
        tag_args = parts[1] if len(parts) > 1 else ''

        if tag_name in self.tags:
            output.append(str(self.tags[tag_name](tag_args, context)))
            return index + 1

        elif tag_name == 'if':
            return self._process_if(tokens, index, context, output)

        elif tag_name == 'for':
            return self._process_for(tokens, index, context, output)

        elif tag_name == 'block':
            block_name = tag_args.strip()
            if block_name in blocks:
                output.append(blocks[block_name])
                # Пропускаем блок до endblock
                while index < len(tokens) and not (
                        tokens[index][0] == 'BLOCK' and
                        tokens[index][1] == 'endblock'
                ):
                    index += 1
            return index + 1

        elif tag_name == 'extends':
            return index + 1  # Обрабатывается в _render_with_inheritance

        return index + 1

    def _process_if(self, tokens, index, context, output):
        """Обработка условного оператора"""
        condition = tokens[index][1][3:].strip()
        result = bool(self._get_variable_value(condition, context))

        # Ищем соответствующий endif
        if_level = 1
        index += 1
        while index < len(tokens) and if_level > 0:
            if tokens[index][0] == 'BLOCK':
                if tokens[index][1].startswith('if '):
                    if_level += 1
                elif tokens[index][1] == 'else' and if_level == 1:
                    result = not result
                elif tokens[index][1] == 'endif':
                    if_level -= 1
            index += 1

        return index

    def _process_for(self, tokens, index, context, output):
        """Обработка цикла for"""
        parts = tokens[index][1][4:].strip().split(' in ')
        if len(parts) != 2:
            return index + 1

        item_var, collection_var = parts
        collection = self._get_variable_value(collection_var, context) or []

        # Ищем соответствующий endfor
        for_start = index
        for_level = 1
        index += 1
        while index < len(tokens) and for_level > 0:
            if tokens[index][0] == 'BLOCK':
                if tokens[index][1].startswith('for '):
                    for_level += 1
                elif tokens[index][1] == 'endfor':
                    for_level -= 1
            index += 1

        # Рендерим цикл
        loop_context = context.copy()
        for item in collection:
            loop_context[item_var] = item
            i = for_start + 1
            while i < index - 1:
                token_type, token_value = tokens[i]
                if token_type == 'TEXT':
                    output.append(token_value)
                elif token_type == 'VAR':
                    output.append(self._resolve_variable(token_value, loop_context))
                elif token_type == 'BLOCK':
                    i = self._process_block(tokens, i, loop_context, output, {})
                    continue
                i += 1

        return index

    def _render_with_inheritance(self, template_content, context):
        """Обработка наследования шаблонов"""
        blocks = {}
        tokens = self._parse_template(template_content)

        # Сначала собираем все блоки из дочернего шаблона
        i = 0
        while i < len(tokens):
            if tokens[i][0] == 'BLOCK' and tokens[i][1].startswith('block '):
                block_name = tokens[i][1][6:].strip()
                block_content = []
                i += 1
                while i < len(tokens) and not (
                        tokens[i][0] == 'BLOCK' and
                        tokens[i][1] == 'endblock'
                ):
                    block_content.append(self._render_token(tokens[i], context))
                    i += 1
                blocks[block_name] = ''.join(block_content)
            elif tokens[i][0] == 'BLOCK' and tokens[i][1].startswith('extends '):
                parent_template = tokens[i][1][8:].strip().strip('"\'')
                break
            i += 1

        # Затем рендерим родительский шаблон с подставленными блоками
        parent_content = self.load_template(parent_template)
        return self.render(parent_content, {**context, 'blocks': blocks})

    def _render_token(self, token, context):
        """Рендеринг отдельного токена"""
        token_type, token_value = token
        if token_type == 'TEXT':
            return token_value
        elif token_type == 'VAR':
            return self._resolve_variable(token_value, context)
        return ''

    # Стандартные теги
    def _tag_now(self, args, context):
        """Тег now для вывода текущей даты"""
        format_str = args.strip() or '%Y-%m-%d %H:%M'
        return datetime.now().strftime(format_str)

    def _tag_include(self, args, context):
        """Тег include для вставки других шаблонов"""
        template_name = args.strip().strip('"\'')
        included_content = self.load_template(template_name)
        return self.render(included_content, context)

    def _tag_block(self, args, context):
        """Тег block (обрабатывается отдельно в _render_with_inheritance)"""
        return ''

    def _tag_extends(self, args, context):
        """Тег extends (обрабатывается отдельно в _render_with_inheritance)"""
        return ''