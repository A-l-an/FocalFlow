package com.google.android.accessibility.utils;

import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.json.JSONTokener;

/** Structural/reference boundary, not a native accessibility or snapshot-freshness judgment. */
final class VirtualTreeValidator {
    static final int MAX_TREE_BYTES = 8 * 1024 * 1024;
    static final int MAX_NODES = 10000;
    static final int MAX_NODE_DEPTH = 128; // root is depth 1
    // A child edge adds both a children object and a node object; metadata adds nesting too.
    private static final int MAX_JSON_DEPTH = 2 * MAX_NODE_DEPTH + 2;
    static final int MAX_MESSAGE_BYTES = MAX_TREE_BYTES + 64 * 1024;
    private static final Pattern UUID_PATTERN = Pattern.compile(
            "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");
    private static final Pattern NUMBER_PATTERN = Pattern.compile(
            "-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?");

    private VirtualTreeValidator() {}

    static JSONObject capture(JSONObject tree) throws JSONException {
        JSONObject copy = copyTree(tree);
        inspectNodes(copy);
        return copy;
    }

    static JSONObject filtered(JSONObject source, JSONObject candidate) throws JSONException {
        if (source == null) throw invalid();
        JSONObject copy = capture(candidate);
        compareNode(source, copy);
        if (inspectNodes(source) > 0 && inspectNodes(copy) == 0) throw invalid();
        return copy;
    }

    static JSONObject copyTree(JSONObject tree) throws JSONException {
        if (tree == null) throw invalid();
        // Inspect iteratively before any recursive serializer/parser: cycles/deep JSON must fail safely.
        ArrayDeque<ValueDepth> pending = new ArrayDeque<>();
        Set<Object> seen = Collections.newSetFromMap(new IdentityHashMap<Object, Boolean>());
        pending.add(new ValueDepth(tree, 1));
        while (!pending.isEmpty()) {
            ValueDepth item = pending.removeLast();
            Object value = item.value;
            if (value instanceof JSONObject || value instanceof JSONArray) {
                if (item.depth > MAX_JSON_DEPTH || !seen.add(value)) throw invalid();
                if (value instanceof JSONObject) {
                    JSONObject object = (JSONObject) value;
                    Iterator<String> keys = object.keys();
                    while (keys.hasNext()) pending.add(new ValueDepth(object.get(keys.next()), item.depth + 1));
                } else {
                    JSONArray array = (JSONArray) value;
                    for (int i = 0; i < array.length(); i++) pending.add(new ValueDepth(array.get(i), item.depth + 1));
                }
            } else if (!(value == JSONObject.NULL || value instanceof String
                    || value instanceof Boolean || value instanceof Number)) {
                throw invalid();
            }
        }
        String serialized = tree.toString();
        if (serialized == null || serialized.getBytes(StandardCharsets.UTF_8).length > MAX_TREE_BYTES) throw invalid();
        return new JSONObject(serialized);
    }

    static int inspectNodes(JSONObject root) throws JSONException {
        Set<String> ids = new HashSet<>();
        Set<String> elementKeys = new HashSet<>();
        ArrayDeque<ValueDepth> pending = new ArrayDeque<>();
        pending.add(new ValueDepth(root, 1));
        int focusCount = 0;
        while (!pending.isEmpty()) {
            ValueDepth item = pending.removeLast();
            JSONObject node = (JSONObject) item.value;
            Object id = node.opt("virtualNodeId");
            if (item.depth > MAX_NODE_DEPTH || !(id instanceof String)
                    || !UUID_PATTERN.matcher((String) id).matches() || !ids.add(((String) id).toLowerCase(Locale.ROOT))
                    || ids.size() > MAX_NODES || !(node.opt("isVirtualFocusNode") instanceof Boolean)) throw invalid();
            if (node.getBoolean("isVirtualFocusNode")) focusCount++;
            if (node.has("children")) {
                Object value = node.get("children");
                if (!(value instanceof JSONObject)) throw invalid();
                JSONObject children = (JSONObject) value;
                Iterator<String> keys = children.keys();
                while (keys.hasNext()) {
                    String key = keys.next();
                    Object child = children.get(key);
                    if (key.trim().isEmpty() || !elementKeys.add(key) || !(child instanceof JSONObject)) throw invalid();
                    pending.add(new ValueDepth(child, item.depth + 1));
                }
            }
        }
        return focusCount;
    }

    private static void compareNode(JSONObject source, JSONObject candidate) throws JSONException {
        sameKeys(source, candidate);
        Iterator<String> keys = source.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            if ("isVirtualFocusNode".equals(key)) continue; // Already checked strict boolean, at a real node only.
            if ("children".equals(key)) {
                JSONObject left = source.getJSONObject(key), right = candidate.getJSONObject(key);
                sameKeys(left, right);
                Iterator<String> childKeys = left.keys();
                while (childKeys.hasNext()) {
                    String childKey = childKeys.next();
                    compareNode(left.getJSONObject(childKey), right.getJSONObject(childKey));
                }
            } else {
                compareValue(source.get(key), candidate.get(key));
            }
        }
    }

    private static void compareValue(Object source, Object candidate) throws JSONException {
        if (source instanceof JSONObject && candidate instanceof JSONObject) {
            JSONObject left = (JSONObject) source, right = (JSONObject) candidate;
            sameKeys(left, right);
            Iterator<String> keys = left.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                compareValue(left.get(key), right.get(key));
            }
        } else if (source instanceof JSONArray && candidate instanceof JSONArray) {
            JSONArray left = (JSONArray) source, right = (JSONArray) candidate;
            if (left.length() != right.length()) throw invalid();
            for (int i = 0; i < left.length(); i++) compareValue(left.get(i), right.get(i));
        } else if (!source.getClass().equals(candidate.getClass()) || !source.equals(candidate)) {
            throw invalid();
        }
    }

    private static void sameKeys(JSONObject left, JSONObject right) {
        if (left.length() != right.length()) throw invalid();
        Iterator<String> keys = left.keys();
        while (keys.hasNext()) if (!right.has(keys.next())) throw invalid();
    }

    private static final class ValueDepth {
        final Object value;
        final int depth;
        ValueDepth(Object value, int depth) { this.value = value; this.depth = depth; }
    }

    static JSONObject parseMessage(String message) throws JSONException {
        if (message == null || message.length() > MAX_MESSAGE_BYTES
                || message.getBytes(StandardCharsets.UTF_8).length > MAX_MESSAGE_BYTES) throw invalid();
        // Android's JSONObject parser can overwrite duplicate keys and accepts trailing text.
        // Read bounded strict JSON here so references cannot be hidden by those parser behaviors.
        JsonReader reader = new JsonReader(message);
        Object result = reader.value(1);
        reader.whitespace();
        if (!(result instanceof JSONObject) || reader.position != message.length()) throw invalid();
        return (JSONObject) result;
    }

    private static IllegalArgumentException invalid() {
        return new IllegalArgumentException("Invalid virtual tree payload");
    }

    private static final class JsonReader {
        final String input;
        int position;
        JsonReader(String input) { this.input = input; }
        void whitespace() {
            while (position < input.length() && " \t\r\n".indexOf(input.charAt(position)) >= 0) position++;
        }
        boolean consume(char expected) {
            whitespace();
            if (position < input.length() && input.charAt(position) == expected) { position++; return true; }
            return false;
        }
        Object value(int depth) throws JSONException {
            whitespace();
            if (position >= input.length()) throw invalid();
            char ch = input.charAt(position);
            if ((ch == '{' || ch == '[') && depth > MAX_JSON_DEPTH + 1) throw invalid();
            if (ch == '"') return string();
            if (consume('{')) {
                JSONObject object = new JSONObject();
                if (consume('}')) return object;
                do {
                    whitespace();
                    String key = string();
                    if (object.has(key) || !consume(':')) throw invalid();
                    object.put(key, value(depth + 1));
                    if (consume('}')) return object;
                } while (consume(','));
                throw invalid();
            }
            if (consume('[')) {
                JSONArray array = new JSONArray();
                if (consume(']')) return array;
                do {
                    array.put(value(depth + 1));
                    if (consume(']')) return array;
                } while (consume(','));
                throw invalid();
            }
            int start = position;
            while (position < input.length() && ",]} \t\r\n".indexOf(input.charAt(position)) < 0) position++;
            String token = input.substring(start, position);
            if ("null".equals(token)) return JSONObject.NULL;
            if ("true".equals(token)) return true;
            if ("false".equals(token)) return false;
            if (!NUMBER_PATTERN.matcher(token).matches()) throw invalid();
            Object number = new JSONTokener(token).nextValue();
            if (!(number instanceof Number) || (Double.isInfinite(((Number) number).doubleValue()) || Double.isNaN(((Number) number).doubleValue()))) throw invalid();
            return number;
        }
        String string() throws JSONException {
            if (position >= input.length() || input.charAt(position) != '"') throw invalid();
            int start = position++;
            while (position < input.length()) {
                char ch = input.charAt(position++);
                if (ch == '"') return (String) new JSONTokener(input.substring(start, position)).nextValue();
                if (ch < 0x20) throw invalid();
                if (ch == '\\') {
                    if (position >= input.length()) throw invalid();
                    char escape = input.charAt(position++);
                    if (escape == 'u') {
                        for (int i = 0; i < 4; i++) {
                            if (position >= input.length() || "0123456789abcdefABCDEF".indexOf(input.charAt(position++)) < 0) throw invalid();
                        }
                    } else if ("\"\\/bfnrt".indexOf(escape) < 0) throw invalid();
                }
            }
            throw invalid();
        }
    }
}
