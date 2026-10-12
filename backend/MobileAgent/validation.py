"""Bounded validation for the existing model sections and Android full-tree contract."""
import copy
import json
import re

# Initial safety limits, not measured performance guarantees.
MAX_MODEL_BYTES = 64 * 1024
MAX_TREE_BYTES = 8 * 1024 * 1024
MAX_UI_NODES = 10000
MAX_UI_DEPTH = 128
MAX_JSON_DEPTH = 512  # A node level contains both a node and a children object.
_UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
_IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')


class ValidationError(ValueError):
    """Static error labels only; never includes model or screen content."""


def require(condition, label):
    if not condition:
        raise ValidationError(label)


def identifier(value):
    require(type(value) in (str, int), 'invalid identifier type')
    value = str(value)
    require(_IDENTIFIER.fullmatch(value) is not None, 'invalid identifier')
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def bounded_json(text, limit):
    require(isinstance(text, str), 'JSON must be text')
    require(len(text) <= limit and len(text.encode('utf-8')) <= limit, 'JSON size limit')
    # Bound nesting before the stdlib recursive parser, respecting quoted strings.
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '{[':
            depth += 1
            require(depth <= MAX_JSON_DEPTH, 'JSON depth limit')
        elif char in '}]':
            depth -= 1
    try:
        return json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=lambda _: require(False, 'nonfinite JSON number'))
    except (ValueError, RecursionError):
        raise ValidationError('invalid JSON') from None


def read_tree(path):
    with open(path, 'rb') as file:
        data = file.read(MAX_TREE_BYTES + 1)
    require(len(data) <= MAX_TREE_BYTES, 'tree size limit')
    try:
        tree = bounded_json(data.decode('utf-8'), MAX_TREE_BYTES)
    except UnicodeError:
        raise ValidationError('invalid tree encoding') from None
    tree_index(tree)
    return tree


def tree_index(tree):
    require(isinstance(tree, dict) and bool(tree), 'invalid root node')
    nodes, uuids = {}, set()
    stack = [(None, tree, 1)]
    count = 0
    while stack:
        alias, node, depth = stack.pop()
        count += 1
        require(count <= MAX_UI_NODES and depth <= MAX_UI_DEPTH, 'tree node/depth limit')
        require(isinstance(node, dict), 'invalid node')
        uid = node.get('virtualNodeId')
        require(isinstance(uid, str) and _UUID.fullmatch(uid) is not None, 'invalid virtual ID')
        require(uid.lower() not in uuids, 'duplicate virtual ID')
        uuids.add(uid.lower())
        require(type(node.get('isVirtualFocusNode')) is bool, 'invalid focus flag')
        if alias is not None:
            require(isinstance(alias, str) and bool(alias.strip()) and alias not in nodes, 'invalid/duplicate element key')
            nodes[alias] = node
        children = node.get('children', {})
        require(isinstance(children, dict), 'invalid children')
        for key, child in children.items():
            stack.append((key, child, depth + 1))
    try:
        serialized = json.dumps(tree, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValidationError('invalid tree JSON') from None
    require(len(serialized.encode('utf-8')) <= MAX_TREE_BYTES, 'tree size limit')
    return nodes


def sections(output, names, empty=()):
    require(isinstance(output, str), 'model response must be text')
    require(len(output) <= MAX_MODEL_BYTES and len(output.encode('utf-8')) <= MAX_MODEL_BYTES, 'model size limit')
    markers = re.findall(r'### [^\r\n]*? ###', output)
    expected = ['### ' + name + ' ###' for name in names]
    require(markers == expected and not output.split(expected[0], 1)[0].strip(), 'invalid model sections')
    result = []
    for index, marker in enumerate(expected):
        value = output.split(marker, 1)[1]
        if index + 1 < len(expected):
            value = value.split(expected[index + 1], 1)[0]
        value = value.strip()
        require(bool(value) or names[index] in empty, 'empty model section')
        result.append(value)
    return result


def json_section(value):
    if value.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```', value)
        require(match is not None, 'invalid JSON fence')
        value = match.group(1)
    return bounded_json(value, MAX_MODEL_BYTES)


def references(values, index, allow_empty=False):
    require(isinstance(values, list) and (allow_empty or bool(values)), 'invalid selection list')
    require(all(isinstance(value, str) and value in index for value in values), 'unknown element reference')
    require(len(values) == len(set(values)), 'duplicate element reference')
    return values


def scoped_index(index, areas):
    scoped = {}
    pending = [(alias, index[alias]) for alias in areas]
    while pending:
        alias, node = pending.pop()
        scoped[alias] = node
        pending.extend(node.get('children', {}).items())
    return scoped


def categories(value, index):
    require(isinstance(value, dict) and bool(value), 'invalid categories')
    for name, members in value.items():
        require(isinstance(name, str) and bool(name.strip()) and name == name.strip(), 'invalid category name')
        require(isinstance(members, dict) and bool(members), 'invalid category members')
        references(list(members), index)
        for alias, info in members.items():
            require(isinstance(info, dict) and set(info) == {'text'}, 'invalid category text')
            # Preserve explicit native nulls without coercing model or source values.
            require(isinstance(info['text'], str) or (
                info['text'] is None and 'text' in index[alias] and index[alias]['text'] is None),
                'invalid category text')
    return value


def selections(value, index):
    require(isinstance(value, list) and bool(value), 'invalid selected UI')
    actions, targets = [], []
    for selection in value:
        require(isinstance(selection, dict) and set(selection) == {'action_point', 'context_elements'}, 'invalid selected UI fields')
        action = selection['action_point']
        references([action], index)
        context = selection['context_elements']
        require(isinstance(context, list), 'invalid context list')
        for item in context:
            require(isinstance(item, dict) and set(item) == {'name', 'text'}, 'invalid context fields')
        names = references([item['name'] for item in context], index, allow_empty=True)
        for item, name in zip(context, names):
            require(isinstance(item['text'], str) or (
                item['text'] is None and 'text' in index[name] and index[name]['text'] is None),
                'invalid context fields')
        actions.append(action)
        targets.extend([action] + names)
    references(actions, index)
    # Legitimate action/context and cross-card overlap retain set-union semantics.
    return list(dict.fromkeys(targets))


def focus_candidate(source, targets):
    index = tree_index(source)
    if isinstance(targets, str):
        targets = [targets]
    elif isinstance(targets, dict):
        targets = list(targets)
    references(targets, index)
    candidate = copy.deepcopy(source)
    candidate_index = tree_index(candidate)
    candidate['isVirtualFocusNode'] = False  # Root has no model element alias.
    selected = set(targets)
    for alias, node in candidate_index.items():
        node['isVirtualFocusNode'] = alias in selected
    # The only writes above are to real-node flags. Verify the complete final tree.
    tree_index(candidate)
    return candidate
