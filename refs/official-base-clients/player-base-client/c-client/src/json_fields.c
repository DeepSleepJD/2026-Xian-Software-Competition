#include "json_fields.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int is_json_whitespace(char ch) {
    return ch == ' ' || ch == '\n' || ch == '\t' || ch == '\r';
}

static const char *skip_json_whitespace(const char *p) {
    while (is_json_whitespace(*p)) {
        p++;
    }
    return p;
}

static void append_char(char *output, size_t output_len, size_t *pos, char ch) {
    if (*pos + 1 < output_len) {
        output[(*pos)++] = ch;
    }
}

static void append_text(char *output, size_t output_len, size_t *pos, const char *text) {
    for (size_t i = 0; text[i] != '\0' && *pos + 1 < output_len; i++) {
        output[(*pos)++] = text[i];
    }
}

static void append_utf8(char *output, size_t output_len, size_t *pos, unsigned int codepoint) {
    if (codepoint <= 0x7F) {
        append_char(output, output_len, pos, (char)codepoint);
    } else if (codepoint <= 0x7FF) {
        append_char(output, output_len, pos, (char)(0xC0 | (codepoint >> 6)));
        append_char(output, output_len, pos, (char)(0x80 | (codepoint & 0x3F)));
    } else {
        append_char(output, output_len, pos, (char)(0xE0 | (codepoint >> 12)));
        append_char(output, output_len, pos, (char)(0x80 | ((codepoint >> 6) & 0x3F)));
        append_char(output, output_len, pos, (char)(0x80 | (codepoint & 0x3F)));
    }
}

static int read_hex4(const char *input, unsigned int *out) {
    char hex[5] = {input[0], input[1], input[2], input[3], '\0'};
    char *end = NULL;
    long value = strtol(hex, &end, 16);
    if (end == hex + 4) {
        *out = (unsigned int)value;
        return 1;
    }
    return 0;
}

static void append_json_escape(char *output, size_t output_len, size_t *pos, char ch) {
    unsigned char byte = (unsigned char)ch;
    switch (ch) {
        case '"':
            append_text(output, output_len, pos, "\\\"");
            break;
        case '\\':
            append_text(output, output_len, pos, "\\\\");
            break;
        case '\b':
            append_text(output, output_len, pos, "\\b");
            break;
        case '\f':
            append_text(output, output_len, pos, "\\f");
            break;
        case '\n':
            append_text(output, output_len, pos, "\\n");
            break;
        case '\r':
            append_text(output, output_len, pos, "\\r");
            break;
        case '\t':
            append_text(output, output_len, pos, "\\t");
            break;
        default:
            if (byte < 0x20) {
                char escaped[7];
                snprintf(escaped, sizeof(escaped), "\\u%04x", byte);
                append_text(output, output_len, pos, escaped);
            } else {
                append_char(output, output_len, pos, ch);
            }
            break;
    }
}

static const char *append_decoded_escape(const char *escape, char *out, size_t out_len, size_t *pos) {
    switch (*escape) {
        case '"':
        case '\\':
        case '/':
            append_char(out, out_len, pos, *escape);
            return escape + 1;
        case 'b':
            append_char(out, out_len, pos, '\b');
            return escape + 1;
        case 'f':
            append_char(out, out_len, pos, '\f');
            return escape + 1;
        case 'n':
            append_char(out, out_len, pos, '\n');
            return escape + 1;
        case 'r':
            append_char(out, out_len, pos, '\r');
            return escape + 1;
        case 't':
            append_char(out, out_len, pos, '\t');
            return escape + 1;
        case 'u': {
            unsigned int codepoint = 0;
            if (read_hex4(escape + 1, &codepoint)) {
                append_utf8(out, out_len, pos, codepoint);
                return escape + 5;
            }
            append_char(out, out_len, pos, *escape);
            return escape + 1;
        }
        default:
            append_char(out, out_len, pos, *escape);
            return escape + 1;
    }
}

static const char *read_json_string(const char *p, char *out, size_t out_len) {
    size_t pos = 0;
    while (*p != '\0' && *p != '"') {
        if (*p == '\\' && p[1] != '\0') {
            p = append_decoded_escape(p + 1, out, out_len, &pos);
        } else {
            append_char(out, out_len, &pos, *p++);
        }
    }
    if (out_len > 0) {
        out[pos] = '\0';
    }
    return p;
}

void json_escape(const char *input, char *output, size_t output_len) {
    size_t pos = 0;
    for (size_t i = 0; input[i] != '\0' && pos + 1 < output_len; i++) {
        append_json_escape(output, output_len, &pos, input[i]);
    }
    if (output_len > 0) {
        output[pos] = '\0';
    }
}

int extract_string_field(const char *json, const char *key, char *out, size_t out_len) {
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(json, pattern);
    if (p == NULL) {
        return 0;
    }
    p = strchr(p + strlen(pattern), ':');
    if (p == NULL) {
        return 0;
    }
    p = skip_json_whitespace(p + 1);
    if (*p != '"') {
        return 0;
    }
    p++;
    const char *end = read_json_string(p, out, out_len);
    return *end == '"';
}

const char *find_object_field(const char *json, const char *key) {
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(json, pattern);
    if (p == NULL) {
        return NULL;
    }
    p = strchr(p + strlen(pattern), ':');
    if (p == NULL) {
        return NULL;
    }
    p = skip_json_whitespace(p + 1);
    return *p == '{' ? p : NULL;
}

static const char *find_direct_field_value(const char *object_json, const char *key) {
    int depth = 0;
    int in_string = 0;
    int escaping = 0;
    size_t key_len = strlen(key);

    for (const char *p = object_json; *p != '\0'; p++) {
        if (in_string) {
            if (escaping) {
                escaping = 0;
            } else if (*p == '\\') {
                escaping = 1;
            } else if (*p == '"') {
                in_string = 0;
            }
            continue;
        }

        if (*p == '"') {
            if (depth != 1) {
                in_string = 1;
                continue;
            }

            const char *token_start = p + 1;
            const char *q = token_start;
            while (*q != '\0') {
                if (*q == '\\' && q[1] != '\0') {
                    q += 2;
                } else if (*q == '"') {
                    break;
                } else {
                    q++;
                }
            }
            if (*q != '"') {
                return NULL;
            }

            const char *after = skip_json_whitespace(q + 1);
            if (*after == ':' && (size_t)(q - token_start) == key_len
                    && strncmp(token_start, key, key_len) == 0) {
                return skip_json_whitespace(after + 1);
            }
            p = q;
        } else if (*p == '{' || *p == '[') {
            depth++;
        } else if (*p == '}' || *p == ']') {
            depth--;
            if (depth <= 0) {
                return NULL;
            }
        }
    }
    return NULL;
}

int extract_direct_string_field(const char *object_json, const char *key, char *out, size_t out_len) {
    const char *p = find_direct_field_value(object_json, key);
    if (p == NULL || *p != '"') {
        return 0;
    }
    p++;
    const char *end = read_json_string(p, out, out_len);
    return *end == '"';
}

int extract_direct_int_field(const char *object_json, const char *key, int *out) {
    const char *p = find_direct_field_value(object_json, key);
    if (p == NULL) {
        return 0;
    }
    char *end = NULL;
    long value = strtol(p, &end, 10);
    if (end == p) {
        return 0;
    }
    *out = (int)value;
    return 1;
}
