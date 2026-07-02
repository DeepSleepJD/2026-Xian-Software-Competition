#include "json_fields.hpp"

#include <cctype>
#include <iomanip>
#include <sstream>

static std::optional<std::size_t> find_direct_field_value(const std::string &object_json, const std::string &key);
static std::string read_string(const std::string &json, std::size_t pos);
static std::string read_object(const std::string &json, std::size_t pos);
static std::size_t find_string_end(const std::string &json, std::size_t start);
static std::size_t skip_whitespace(const std::string &json, std::size_t pos);
static void append_decoded_escape(const std::string &json, std::size_t &pos, std::string &out);
static void append_json_escape(std::string &out, char ch);
static void append_utf8(std::string &out, unsigned int codepoint);
static bool read_hex4(const std::string &json, std::size_t start, unsigned int &codepoint);
static std::string unicode_escape(unsigned char ch);

std::string json_escape(const std::string &value) {
    std::string out;
    for (char ch : value) {
        append_json_escape(out, ch);
    }
    return out;
}

std::optional<std::string> extract_string_field(const std::string &json, const std::string &key) {
    std::string pattern = "\"" + key + "\"";
    std::size_t pos = json.find(pattern);
    if (pos == std::string::npos) {
        return std::nullopt;
    }
    pos = json.find(':', pos + pattern.size());
    if (pos == std::string::npos) {
        return std::nullopt;
    }
    pos = skip_whitespace(json, pos + 1);
    if (pos >= json.size() || json[pos] != '"') {
        return std::nullopt;
    }
    return read_string(json, pos + 1);
}

std::optional<std::string> extract_object_field(const std::string &json, const std::string &key) {
    std::string pattern = "\"" + key + "\"";
    std::size_t pos = json.find(pattern);
    if (pos == std::string::npos) {
        return std::nullopt;
    }
    pos = json.find(':', pos + pattern.size());
    if (pos == std::string::npos) {
        return std::nullopt;
    }
    pos = skip_whitespace(json, pos + 1);
    if (pos >= json.size() || json[pos] != '{') {
        return std::nullopt;
    }
    return read_object(json, pos);
}

static std::optional<std::size_t> find_direct_field_value(const std::string &object_json, const std::string &key) {
    int depth = 0;
    bool in_string = false;
    bool escaping = false;

    for (std::size_t pos = 0; pos < object_json.size(); ++pos) {
        char ch = object_json[pos];
        if (in_string) {
            if (escaping) {
                escaping = false;
            } else if (ch == '\\') {
                escaping = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }

        if (ch == '"') {
            if (depth != 1) {
                in_string = true;
                continue;
            }

            std::size_t token_start = pos + 1;
            std::size_t end = find_string_end(object_json, token_start);
            if (end >= object_json.size()) {
                return std::nullopt;
            }

            std::size_t after = skip_whitespace(object_json, end + 1);
            if (after < object_json.size() && object_json[after] == ':'
                    && object_json.compare(token_start, end - token_start, key) == 0) {
                return skip_whitespace(object_json, after + 1);
            }
            pos = end;
        } else if (ch == '{' || ch == '[') {
            ++depth;
        } else if (ch == '}' || ch == ']') {
            --depth;
            if (depth <= 0) {
                return std::nullopt;
            }
        }
    }
    return std::nullopt;
}

std::optional<std::string> extract_direct_string_field(const std::string &object_json, const std::string &key) {
    auto pos = find_direct_field_value(object_json, key);
    if (!pos.has_value() || *pos >= object_json.size() || object_json[*pos] != '"') {
        return std::nullopt;
    }
    return read_string(object_json, *pos + 1);
}

std::optional<int> extract_direct_int_field(const std::string &object_json, const std::string &key) {
    auto pos = find_direct_field_value(object_json, key);
    if (!pos.has_value()) {
        return std::nullopt;
    }
    std::size_t end = *pos;
    while (end < object_json.size()
            && (std::isdigit(static_cast<unsigned char>(object_json[end])) || object_json[end] == '-')) {
        ++end;
    }
    if (end == *pos) {
        return std::nullopt;
    }
    return std::stoi(object_json.substr(*pos, end - *pos));
}

static std::string read_string(const std::string &json, std::size_t pos) {
    std::string out;
    while (pos < json.size() && json[pos] != '"') {
        if (json[pos] == '\\' && pos + 1 < json.size()) {
            ++pos;
            append_decoded_escape(json, pos, out);
            continue;
        }
        out.push_back(json[pos++]);
    }
    return out;
}

static void append_decoded_escape(const std::string &json, std::size_t &pos, std::string &out) {
    char escaped = json[pos];
    switch (escaped) {
        case '"':
        case '\\':
        case '/':
            out.push_back(escaped);
            ++pos;
            break;
        case 'b':
            out.push_back('\b');
            ++pos;
            break;
        case 'f':
            out.push_back('\f');
            ++pos;
            break;
        case 'n':
            out.push_back('\n');
            ++pos;
            break;
        case 'r':
            out.push_back('\r');
            ++pos;
            break;
        case 't':
            out.push_back('\t');
            ++pos;
            break;
        case 'u': {
            unsigned int codepoint = 0;
            if (read_hex4(json, pos + 1, codepoint)) {
                append_utf8(out, codepoint);
                pos += 5;
            } else {
                out.push_back(escaped);
                ++pos;
            }
            break;
        }
        default:
            out.push_back(escaped);
            ++pos;
            break;
    }
}

static void append_json_escape(std::string &out, char ch) {
    switch (ch) {
        case '"':
            out += "\\\"";
            break;
        case '\\':
            out += "\\\\";
            break;
        case '\b':
            out += "\\b";
            break;
        case '\f':
            out += "\\f";
            break;
        case '\n':
            out += "\\n";
            break;
        case '\r':
            out += "\\r";
            break;
        case '\t':
            out += "\\t";
            break;
        default:
            if (static_cast<unsigned char>(ch) < 0x20) {
                out += unicode_escape(static_cast<unsigned char>(ch));
            } else {
                out.push_back(ch);
            }
            break;
    }
}

static void append_utf8(std::string &out, unsigned int codepoint) {
    if (codepoint <= 0x7F) {
        out.push_back(static_cast<char>(codepoint));
    } else if (codepoint <= 0x7FF) {
        out.push_back(static_cast<char>(0xC0 | (codepoint >> 6)));
        out.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else {
        out.push_back(static_cast<char>(0xE0 | (codepoint >> 12)));
        out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    }
}

static bool read_hex4(const std::string &json, std::size_t start, unsigned int &codepoint) {
    if (start + 4 > json.size()) {
        return false;
    }
    codepoint = 0;
    for (std::size_t pos = start; pos < start + 4; ++pos) {
        unsigned char ch = static_cast<unsigned char>(json[pos]);
        if (!std::isxdigit(ch)) {
            return false;
        }
        codepoint *= 16;
        if (std::isdigit(ch)) {
            codepoint += ch - '0';
        } else {
            codepoint += static_cast<unsigned int>(std::tolower(ch) - 'a' + 10);
        }
    }
    return true;
}

static std::string unicode_escape(unsigned char ch) {
    std::ostringstream escaped;
    escaped << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(ch);
    return escaped.str();
}

static std::string read_object(const std::string &json, std::size_t pos) {
    int depth = 0;
    bool in_string = false;
    bool escaping = false;
    for (std::size_t end = pos; end < json.size(); ++end) {
        char ch = json[end];
        if (in_string) {
            if (escaping) {
                escaping = false;
            } else if (ch == '\\') {
                escaping = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }
        if (ch == '"') {
            in_string = true;
        } else if (ch == '{') {
            ++depth;
        } else if (ch == '}') {
            --depth;
            if (depth == 0) {
                return json.substr(pos, end - pos + 1);
            }
        }
    }
    return json;
}

static std::size_t find_string_end(const std::string &json, std::size_t start) {
    std::size_t pos = start;
    while (pos < json.size()) {
        if (json[pos] == '\\' && pos + 1 < json.size()) {
            pos += 2;
        } else if (json[pos] == '"') {
            return pos;
        } else {
            ++pos;
        }
    }
    return pos;
}

static std::size_t skip_whitespace(const std::string &json, std::size_t pos) {
    while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) {
        ++pos;
    }
    return pos;
}
