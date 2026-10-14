/* Release generator embeds a source-built Maylang installer and bundle here.
 * Build the generated single file with: cc -std=c11 -O2 bootstrap.c -o install
 * No interpreter, compression library, shell command, or network is used here.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <dirent.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static const char payload[] = ""
/* MAYLANG_PAYLOAD */
;
static volatile sig_atomic_t child_pid;
static volatile sig_atomic_t interrupted;

static void interrupt_child(int number) {
    interrupted = number;
    if (child_pid > 0) kill((pid_t)child_pid, number);
}

static int remove_tree(const char *path) {
    struct stat info;
    if (lstat(path, &info) < 0) return errno == ENOENT ? 0 : -1;
    if (!S_ISDIR(info.st_mode)) return unlink(path);
    DIR *directory = opendir(path);
    if (!directory) return -1;
    int result = 0;
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char next[PATH_MAX];
        if (snprintf(next, sizeof next, "%s/%s", path, entry->d_name) >= (int)sizeof next || remove_tree(next) < 0) result = -1;
    }
    if (closedir(directory) < 0 || rmdir(path) < 0) result = -1;
    return result;
}

static int digit(unsigned char value) {
    if (value >= 'A' && value <= 'Z') return value - 'A';
    if (value >= 'a' && value <= 'z') return value - 'a' + 26;
    if (value >= '0' && value <= '9') return value - '0' + 52;
    if (value == '+') return 62;
    if (value == '/') return 63;
    return -1;
}

static unsigned char *decode(size_t *length) {
    size_t count = sizeof payload - 1;
    if (count % 4) return NULL;
    unsigned char *data = malloc(count / 4 * 3 + 1);
    if (!data) return NULL;
    *length = 0;
    for (size_t i = 0; i < count; i += 4) {
        int a = digit(payload[i]), b = digit(payload[i + 1]);
        int c = payload[i + 2] == '=' ? 0 : digit(payload[i + 2]);
        int d = payload[i + 3] == '=' ? 0 : digit(payload[i + 3]);
        if (a < 0 || b < 0 || c < 0 || d < 0 ||
            (payload[i + 2] == '=' && payload[i + 3] != '=') ||
            ((payload[i + 2] == '=' || payload[i + 3] == '=') && i + 4 != count)) {
            free(data); return NULL;
        }
        uint32_t value = (uint32_t)a << 18 | (uint32_t)b << 12 | (uint32_t)c << 6 | (uint32_t)d;
        data[(*length)++] = value >> 16;
        if (payload[i + 2] != '=') data[(*length)++] = value >> 8;
        if (payload[i + 3] != '=') data[(*length)++] = value;
    }
    return data;
}

static uint32_t little32(const unsigned char *data) {
    return (uint32_t)data[0] | (uint32_t)data[1] << 8 | (uint32_t)data[2] << 16 | (uint32_t)data[3] << 24;
}

static int safe_name(const char *name) {
    if (!*name || *name == '/') return 0;
    const char *part = name;
    while (*part) {
        const char *end = strchr(part, '/');
        size_t count = end ? (size_t)(end - part) : strlen(part);
        if (!count || (count == 1 && part[0] == '.') || (count == 2 && part[0] == '.' && part[1] == '.')) return 0;
        if (!end) break;
        part = end + 1;
        if (!*part) return 0;
    }
    return 1;
}

static int unpack(const char *root, const unsigned char *data, size_t length) {
    if (length < 12 || memcmp(data, "MAYINST1", 8)) return -1;
    uint32_t files = little32(data + 8);
    size_t offset = 12;
    for (uint32_t i = 0; i < files; i++) {
        if (length - offset < 12) return -1;
        uint32_t name_size = little32(data + offset), mode = little32(data + offset + 4), size = little32(data + offset + 8);
        offset += 12;
        if (!name_size || name_size >= PATH_MAX || name_size > length - offset || size > length - offset - name_size ||
            memchr(data + offset, 0, name_size) || (mode != 0644 && mode != 0755)) return -1;
        char name[PATH_MAX], path[PATH_MAX];
        memcpy(name, data + offset, name_size); name[name_size] = 0;
        if (!safe_name(name) || snprintf(path, sizeof path, "%s/%s", root, name) >= (int)sizeof path) return -1;
        offset += name_size;
        for (char *slash = path + strlen(root) + 1; *slash; slash++) {
            if (*slash != '/') continue;
            *slash = 0;
            struct stat info;
            if ((mkdir(path, 0700) < 0 && errno != EEXIST) || lstat(path, &info) < 0 || !S_ISDIR(info.st_mode)) return -1;
            *slash = '/';
        }
        int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, mode);
        if (fd < 0) return -1;
        size_t written = 0;
        while (written < size) {
            ssize_t count = write(fd, data + offset + written, size - written);
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) { close(fd); return -1; }
            written += (size_t)count;
        }
        if (fchmod(fd, mode) < 0) { close(fd); return -1; }
        if (close(fd) < 0) return -1;
        offset += size;
    }
    return offset == length ? 0 : -1;
}

int main(int argc, char **argv) {
#if !defined(__linux__) || !defined(__x86_64__)
    (void)argc; (void)argv;
    fputs("Maylang installer requires Linux x86-64 (including WSL 2).\n", stderr);
    return 1;
#else
    const char *temporary = getenv("TMPDIR");
    if (!temporary || !*temporary) temporary = "/tmp";
    char root[PATH_MAX];
    if (snprintf(root, sizeof root, "%s/maylang-install-XXXXXX", temporary) >= (int)sizeof root || !mkdtemp(root)) {
        perror("maylang-bootstrap: staging directory"); return 1;
    }
    size_t length;
    unsigned char *data = decode(&length);
    int result = 1;
    if (!data || unpack(root, data, length) < 0) {
        fputs("maylang-bootstrap: invalid or unwritable embedded bundle\n", stderr);
        free(data); remove_tree(root); return 1;
    }
    free(data);
    char installer[PATH_MAX], bundle[PATH_MAX];
    if (snprintf(installer, sizeof installer, "%s/bundle/bin/may-installer", root) >= (int)sizeof installer ||
        snprintf(bundle, sizeof bundle, "%s/bundle", root) >= (int)sizeof bundle) { remove_tree(root); return 1; }
    char **arguments = calloc((size_t)argc + 3, sizeof *arguments);
    if (!arguments) { remove_tree(root); return 1; }
    arguments[0] = installer; arguments[1] = "--bundle"; arguments[2] = bundle;
    for (int i = 1; i < argc; i++) arguments[i + 2] = argv[i];
    struct sigaction action = {0}; action.sa_handler = interrupt_child;
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL); sigaction(SIGTERM, &action, NULL);
    pid_t child = fork();
    if (child == 0) {
        signal(SIGINT, SIG_DFL); signal(SIGTERM, SIG_DFL);
        execv(installer, arguments); perror("maylang-bootstrap: exec installer"); _exit(127);
    }
    if (child < 0) perror("maylang-bootstrap: fork");
    else {
        child_pid = child;
        if (interrupted) kill(child, interrupted);
        int status; pid_t waited;
        do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
        if (waited > 0) result = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
        child_pid = 0;
    }
    free(arguments);
    if (remove_tree(root) < 0) { perror("maylang-bootstrap: cleanup"); if (!result) result = 1; }
    return result;
#endif
}
