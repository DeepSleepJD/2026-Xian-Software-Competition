#ifndef LYCHEE_JSON_FIELDS_H
#define LYCHEE_JSON_FIELDS_H

#include <stddef.h>

void json_escape(const char *input, char *output, size_t output_len);
int extract_string_field(const char *json, const char *key, char *out, size_t out_len);
const char *find_object_field(const char *json, const char *key);
int extract_direct_string_field(const char *object_json, const char *key, char *out, size_t out_len);
int extract_direct_int_field(const char *object_json, const char *key, int *out);

#endif
