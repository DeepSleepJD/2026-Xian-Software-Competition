#ifndef LYCHEE_JSON_FIELDS_HPP
#define LYCHEE_JSON_FIELDS_HPP

#include <optional>
#include <string>

std::string json_escape(const std::string &value);
std::optional<std::string> extract_string_field(const std::string &json, const std::string &key);
std::optional<std::string> extract_object_field(const std::string &json, const std::string &key);
std::optional<std::string> extract_direct_string_field(const std::string &object_json, const std::string &key);
std::optional<int> extract_direct_int_field(const std::string &object_json, const std::string &key);

#endif
