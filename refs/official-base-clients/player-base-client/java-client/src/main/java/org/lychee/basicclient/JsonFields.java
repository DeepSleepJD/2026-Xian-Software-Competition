package org.lychee.basicclient;

public final class JsonFields {
    private JsonFields() {
    }

    public static String escape(String value) {
        if (value == null) {
            return "";
        }
        StringBuilder out = new StringBuilder(value.length() + 16);
        for (int i = 0; i < value.length(); i++) {
            char ch = value.charAt(i);
            switch (ch) {
                case '"':
                case '\\':
                    out.append('\\').append(ch);
                    break;
                case '\b':
                    out.append("\\b");
                    break;
                case '\f':
                    out.append("\\f");
                    break;
                case '\n':
                    out.append("\\n");
                    break;
                case '\r':
                    out.append("\\r");
                    break;
                case '\t':
                    out.append("\\t");
                    break;
                default:
                    if (ch < 0x20) {
                        out.append(String.format("\\u%04x", (int) ch));
                    } else {
                        out.append(ch);
                    }
                    break;
            }
        }
        return out.toString();
    }

    public static String extractStringField(String json, String key) {
        String pattern = "\"" + key + "\"";
        int pos = json.indexOf(pattern);
        if (pos < 0) {
            return "";
        }
        pos = json.indexOf(':', pos + pattern.length());
        if (pos < 0) {
            return "";
        }
        pos++;
        while (pos < json.length() && Character.isWhitespace(json.charAt(pos))) {
            pos++;
        }
        if (pos >= json.length() || json.charAt(pos) != '"') {
            return "";
        }
        return readString(json, pos + 1);
    }

    public static String extractObjectField(String json, String key) {
        String pattern = "\"" + key + "\"";
        int pos = json.indexOf(pattern);
        if (pos < 0) {
            return json;
        }
        pos = json.indexOf(':', pos + pattern.length());
        if (pos < 0) {
            return json;
        }
        pos++;
        while (pos < json.length() && Character.isWhitespace(json.charAt(pos))) {
            pos++;
        }
        if (pos >= json.length() || json.charAt(pos) != '{') {
            return json;
        }
        return readObject(json, pos);
    }

    public static String extractDirectStringField(String objectJson, String key) {
        int pos = findDirectFieldValue(objectJson, key);
        if (pos < 0 || pos >= objectJson.length() || objectJson.charAt(pos) != '"') {
            return "";
        }
        return readString(objectJson, pos + 1);
    }

    public static int extractDirectIntField(String objectJson, String key, int fallback) {
        int pos = findDirectFieldValue(objectJson, key);
        if (pos < 0) {
            return fallback;
        }
        int end = pos;
        while (end < objectJson.length()
                && (Character.isDigit(objectJson.charAt(end)) || objectJson.charAt(end) == '-')) {
            end++;
        }
        if (end == pos) {
            return fallback;
        }
        return Integer.parseInt(objectJson.substring(pos, end));
    }

    private static String readString(String json, int pos) {
        StringBuilder out = new StringBuilder();
        while (pos < json.length() && json.charAt(pos) != '"') {
            char ch = json.charAt(pos);
            if (ch == '\\' && pos + 1 < json.length()) {
                char escaped = json.charAt(pos + 1);
                if (escaped == 'u' && pos + 5 < json.length()) {
                    out.append((char) Integer.parseInt(json.substring(pos + 2, pos + 6), 16));
                    pos += 6;
                    continue;
                }
                out.append(readEscapedCharacter(escaped));
                pos += 2;
                continue;
            } else {
                out.append(ch);
            }
            pos++;
        }
        return out.toString();
    }

    private static char readEscapedCharacter(char escaped) {
        switch (escaped) {
            case '"':
            case '\\':
            case '/':
                return escaped;
            case 'b':
                return '\b';
            case 'f':
                return '\f';
            case 'n':
                return '\n';
            case 'r':
                return '\r';
            case 't':
                return '\t';
            default:
                return escaped;
        }
    }

    private static String readObject(String json, int pos) {
        int depth = 0;
        boolean inString = false;
        boolean escaping = false;
        for (int end = pos; end < json.length(); end++) {
            char ch = json.charAt(end);
            if (inString) {
                if (escaping) {
                    escaping = false;
                } else if (ch == '\\') {
                    escaping = true;
                } else if (ch == '"') {
                    inString = false;
                }
                continue;
            }
            if (ch == '"') {
                inString = true;
            } else if (ch == '{') {
                depth++;
            } else if (ch == '}') {
                depth--;
                if (depth == 0) {
                    return json.substring(pos, end + 1);
                }
            }
        }
        return json;
    }

    private static int findDirectFieldValue(String objectJson, String key) {
        int depth = 0;
        boolean inString = false;
        boolean escaping = false;

        for (int pos = 0; pos < objectJson.length(); pos++) {
            char ch = objectJson.charAt(pos);
            if (inString) {
                if (escaping) {
                    escaping = false;
                } else if (ch == '\\') {
                    escaping = true;
                } else if (ch == '"') {
                    inString = false;
                }
                continue;
            }

            if (ch == '"') {
                if (depth != 1) {
                    inString = true;
                    continue;
                }

                int tokenStart = pos + 1;
                int end = findStringEnd(objectJson, tokenStart);
                if (end >= objectJson.length()) {
                    return -1;
                }

                int after = skipWhitespace(objectJson, end + 1);
                if (after < objectJson.length() && objectJson.charAt(after) == ':'
                        && objectJson.substring(tokenStart, end).equals(key)) {
                    return skipWhitespace(objectJson, after + 1);
                }
                pos = end;
            } else if (ch == '{' || ch == '[') {
                depth++;
            } else if (ch == '}' || ch == ']') {
                depth--;
                if (depth <= 0) {
                    return -1;
                }
            }
        }
        return -1;
    }

    private static int findStringEnd(String json, int start) {
        int pos = start;
        while (pos < json.length()) {
            char ch = json.charAt(pos);
            if (ch == '\\' && pos + 1 < json.length()) {
                pos += 2;
            } else if (ch == '"') {
                return pos;
            } else {
                pos++;
            }
        }
        return pos;
    }

    private static int skipWhitespace(String json, int pos) {
        while (pos < json.length() && Character.isWhitespace(json.charAt(pos))) {
            pos++;
        }
        return pos;
    }
}
