/* Shared immutable draw packet. Only the Sokol thread touches graphics APIs. */
#ifndef MAYUI_RENDER_H
#define MAYUI_RENDER_H
#include <stddef.h>
#include <stdint.h>
typedef struct {
    float position[2], uv[2], color[4], shape[4], style[2];
} MuiVertex;
void mui_window_present(const unsigned char *, long, long);
void mui_window_submit(const MuiVertex *, size_t, const unsigned char *, int, int, uint64_t, int, int);
#endif
