#define _XOPEN_SOURCE 700
#define _POSIX_C_SOURCE 200809L
#include "vendor/binjnes/emulator.h"
#include <errno.h>
#include <limits.h>
#include <inttypes.h>
#include <math.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include "audio.h"
#include "demo.h"
static Emulator *machine;
static FileData cartridge;
static RGBAFrameBuffer framebuffer;
static unsigned buttons;
static uint64_t rom_hash, frames, generated_samples;
static long audio_peak;
static char message[1024], title[256], loaded_path[PATH_MAX], save_dir[PATH_MAX];
static uint64_t hash_data(const void *data, size_t size) {
    uint64_t h=UINT64_C(14695981039346656037);
    const unsigned char *p=data;
    while (size--) { h^=*p++; h*=UINT64_C(1099511628211); }
    return h;
}
static void input_callback(SystemInput *input, void *user, bool strobe) {
    (void)user; (void)strobe; memset(input,0,sizeof(*input));
    input->port[0].type=CONTROLLER_JOYPAD;
    input->port[0].joyp=(JoypadInput){.A=buttons&1,.B=buttons&2,.select=buttons&4,.start=buttons&8,
        .up=buttons&16,.down=buttons&32,.left=buttons&64,.right=buttons&128};
}
static int make_dirs(const char *path) {
    char temp[PATH_MAX];
    if (snprintf(temp,sizeof(temp),"%s",path)>=(int)sizeof(temp)) return 0;
    for (char *p=temp+1; *p; p++) if (*p=='/') { *p=0; if (mkdir(temp,0700) && errno!=EEXIST) return 0; *p='/'; }
    return mkdir(temp,0700)==0 || errno==EEXIST;
}
static int storage_path(char *out, const char *suffix) {
    if (!save_dir[0]) {
        const char *base=getenv("XDG_DATA_HOME");
        if (base && base[0]=='/') snprintf(save_dir,sizeof(save_dir),"%s/maynes",base);
        else { base=getenv("HOME"); if (!base) return 0; snprintf(save_dir,sizeof(save_dir),"%s/.local/share/maynes",base); }
    }
    if (!make_dirs(save_dir)) return 0;
    return snprintf(out,PATH_MAX,"%s/%016" PRIx64 ".%s",save_dir,rom_hash,suffix)<PATH_MAX;
}
static int atomic_write(const char *path,const void *data,size_t size) {
    char temp[PATH_MAX];
    if (snprintf(temp,sizeof(temp),"%s.XXXXXX",path)>=PATH_MAX) return 0;
    int fd=mkstemp(temp); if (fd<0) return 0;
    const unsigned char *p=data; size_t left=size;
    while (left) { ssize_t n=write(fd,p,left); if (n<0 && errno==EINTR) continue; if (n<=0) break; p+=n; left-=(size_t)n; }
    int ok=!left && !fsync(fd); if (close(fd)) ok=0;
    if (ok && !rename(temp,path)) return 1;
    unlink(temp); return 0;
}
static void save_battery(void) {
    if (!machine || !machine->ci.has_bat_ram) return;
    char path[PATH_MAX]; FileData data={0};
    emulator_init_prg_ram_file_data(machine,&data);
    if (data.data && storage_path(path,"sav") && emulator_write_prg_ram(machine,&data)==OK) {
        if (!atomic_write(path,data.data,data.size)) snprintf(message,sizeof(message),"Could not write cartridge battery save");
    }
    file_data_delete(&data);
}
const char *nes_message(void) { return message; }
const char *nes_title(void) { return title; }
const char *nes_path(void) { return loaded_path; }
const char *nes_storage(void) { char path[PATH_MAX]; storage_path(path,"state"); return save_dir; }
void *nes_pixels(void) { return framebuffer; }
long nes_frame_count(void) { return (long)frames; }
long nes_mapper(void) { return machine ? machine->ci.mapper : -1; }
long nes_period_us(void) { return machine ? (long)((uint64_t)machine->master_ticks_per_frame*1000000/machine->master_ticks_per_second) : 16639; }
long nes_frame_hash(void) { return (long)(hash_data(framebuffer,sizeof(framebuffer)) & UINT64_C(0x0fffffffffffffff)); }
long nes_audio_samples(void) { return (long)generated_samples; }
long nes_audio_peak(void) { return audio_peak; }
long nes_audio_status(void) { return atomic_load(&audio_status); }
void nes_audio(long enabled) { if (enabled) audio_start(); atomic_store(&audio_muted,!enabled); if (!enabled) audio_clear(); }
void nes_audio_clear(void) { audio_clear(); }
long nes_load(const char *path) {
    FileData data={0};
    if (!path[0]) { data.size=sizeof(demo_rom); data.data=malloc(data.size); if (data.data) memcpy(data.data,demo_rom,data.size); }
    else {
        FILE *f=fopen(path,"rb");
        if (!f) { snprintf(message,sizeof(message),"Cannot open ROM: %s",strerror(errno)); return 0; }
        if (fseek(f,0,SEEK_END)) { fclose(f); return 0; }
        long size=ftell(f); rewind(f);
        if (size<16 || size>8*1024*1024) { fclose(f); snprintf(message,sizeof(message),"Expected a .nes cartridge between 16 bytes and 8 MiB"); return 0; }
        data.size=(size_t)size; data.data=malloc(data.size);
        if (!data.data || fread(data.data,1,data.size,f)!=data.size) { fclose(f); free(data.data); snprintf(message,sizeof(message),"Could not read ROM"); return 0; }
        fclose(f);
    }
    if (!data.data) { snprintf(message,sizeof(message),"Cannot allocate ROM"); return 0; }
    unsigned char *h=data.data;
    if (data.size<16 || memcmp(h,"NES\x1a",4) || (h[7]&12)!=0 || !h[4] ||
        data.size<16u+((h[6]&4)?512u:0u)+(size_t)h[4]*16384+(size_t)h[5]*8192) {
        free(data.data); snprintf(message,sizeof(message),"Invalid or truncated cartridge. Open an uncompressed iNES 1.0 .nes file."); return 0;
    }
    EmulatorInit init={.rom=data,.audio_frequency=48000,.audio_frames=512,.ram_init=RAM_INIT_ZERO,.random_seed=1};
    Emulator *next=emulator_new(&init);
    if (!next) { free(data.data); snprintf(message,sizeof(message),"This cartridge mapper or layout is unsupported"); return 0; }
    save_battery(); emulator_delete(machine); free(cartridge.data);
    machine=next; cartridge=data; rom_hash=hash_data(data.data,data.size); frames=0; buttons=0; generated_samples=0; audio_peak=0;
    memset(framebuffer,0,sizeof(framebuffer)); audio_clear();
    emulator_set_joypad_callback(machine,input_callback,NULL);
    if (!path[0] || !realpath(path,loaded_path)) snprintf(loaded_path,sizeof(loaded_path),"%s",path);
    const char *base=strrchr(path,'/'); base=base ? base+1 : path;
    snprintf(title,sizeof(title),"%s",path[0] ? base : "Starfall");
    char battery[PATH_MAX];
    if (machine->ci.has_bat_ram && storage_path(battery,"sav") && access(battery,F_OK)==0) {
        if (emulator_read_prg_ram_from_file(machine,battery)!=OK) snprintf(message,sizeof(message),"Battery save could not be restored");
    }
    snprintf(message,sizeof(message),"%s",path[0] ? "Cartridge loaded · ready to play" : "Catch the falling stars. Arrows move, X boosts, Enter restarts.");
    return 1;
}
long nes_frame(long input) {
    if (!machine) return 0; buttons=(unsigned)input;
    Ticks limit=emulator_get_ticks(machine)+machine->master_ticks_per_frame*2;
    for (;;) {
        EmulatorEvent event=emulator_run_until(machine,limit);
        if (event&EMULATOR_EVENT_AUDIO_BUFFER_FULL) {
            AudioBuffer *a=emulator_get_audio_buffer(machine);
            unsigned count=audio_buffer_get_frames(a);
            generated_samples+=count;
            for (unsigned i=0; i<count; i++) {
                long peak=(long)(fabsf(a->data[i])*1000000);
                if (peak>audio_peak) audio_peak=peak;
            }
            audio_push(a->data,count);
        }
        if (event&EMULATOR_EVENT_INVALID_OPCODE) { snprintf(message,sizeof(message),"Cartridge stopped on an invalid CPU instruction"); return 0; }
        if (event&EMULATOR_EVENT_NEW_FRAME) { emulator_convert_frame_buffer(machine,framebuffer); frames++; return 1; }
        if (event&EMULATOR_EVENT_UNTIL_TICKS) { snprintf(message,sizeof(message),"Cartridge did not produce a video frame"); return 0; }
    }
}
long nes_reset(void) {
    if (!machine) return 0;
    emulator_set_reset(machine,true);
    long ok=nes_frame(0);
    emulator_set_reset(machine,false); audio_clear();
    snprintf(message,sizeof(message),"Console reset"); return ok;
}
/* State envelope binds states to the exact ROM and detects partial/corrupt writes.
 * Core serializes pointer-free machine state; never persist host pointer graphs. */
typedef struct { char magic[8]; uint64_t rom, checksum, size, frames; } StateHeader;
long nes_save(void) {
    if (!machine) return 0;
    FileData state={0}; emulator_init_state_file_data(&state);
    char path[PATH_MAX]; int ok=0;
    if (state.data && emulator_write_state(machine,&state)==OK && storage_path(path,"state")) {
        size_t total=state.size+sizeof(machine->frame_buffer)+sizeof(framebuffer);
        unsigned char *data=malloc(sizeof(StateHeader)+total);
        if (data) {
            unsigned char *body=data+sizeof(StateHeader);
            memcpy(body,state.data,state.size);
            memcpy(body+state.size,machine->frame_buffer,sizeof(machine->frame_buffer));
            memcpy(body+state.size+sizeof(machine->frame_buffer),framebuffer,sizeof(framebuffer));
            StateHeader h={.magic="MAYNES1",.rom=rom_hash,.checksum=hash_data(body,total),.size=total,.frames=frames};
            memcpy(data,&h,sizeof(h)); ok=atomic_write(path,data,sizeof(h)+total); free(data);
        }
    }
    file_data_delete(&state); save_battery();
    snprintf(message,sizeof(message),"%s",ok ? "Saved state · F8 to resume from here" : "Could not write save state"); return ok;
}
long nes_restore(void) {
    if (!machine) return 0;
    char path[PATH_MAX]; FileData state={0}; int ok=0;
    if (storage_path(path,"state")) {
        FILE *file=fopen(path,"rb");
        if (file) {
            StateHeader h; emulator_init_state_file_data(&state);
            size_t total=state.size+sizeof(machine->frame_buffer)+sizeof(framebuffer);
            unsigned char *body=malloc(total);
            if (body && fread(&h,1,sizeof(h),file)==sizeof(h) && !memcmp(h.magic,"MAYNES1",8) && h.rom==rom_hash && h.size==total &&
                fread(body,1,total,file)==total && fgetc(file)==EOF && hash_data(body,total)==h.checksum) {
                memcpy(state.data,body,state.size);
                ok=emulator_read_state(machine,&state)==OK;
                if (ok) {
                    frames=h.frames; audio_clear();
                    memcpy(machine->frame_buffer,body+state.size,sizeof(machine->frame_buffer));
                    memcpy(framebuffer,body+state.size+sizeof(machine->frame_buffer),sizeof(framebuffer));
                }
            }
            free(body);
            fclose(file);
        }
    }
    file_data_delete(&state);
    snprintf(message,sizeof(message),"%s",ok ? "State restored" : "No valid save for this cartridge. Save with F5 first."); return ok;
}
void nes_battery_flush(void) { save_battery(); }
void nes_close(void) { save_battery(); audio_close(); emulator_delete(machine); machine=NULL; free(cartridge.data); cartridge=(FileData){0}; }
const char *nes_pick_rom(void) {
    static char path[PATH_MAX]; path[0]=0;
    int fd[2]; if (pipe(fd)) return path;
    const char *initial=loaded_path[0] ? loaded_path : getenv("HOME");
    pid_t pid=fork();
    if (pid==0) {
        close(fd[0]); dup2(fd[1],STDOUT_FILENO); close(fd[1]);
        execlp("zenity","zenity","--file-selection","--title=Open NES cartridge","--filename",initial ? initial : "/","--file-filter=NES cartridges | *.nes *.NES","--file-filter=All files | *",(char*)NULL);
        _exit(127);
    }
    close(fd[1]);
    if (pid<0) { close(fd[0]); return path; }
    size_t size=0;
    while (size<sizeof(path)-1) { ssize_t n=read(fd[0],path+size,sizeof(path)-1-size); if (n<0 && errno==EINTR) continue; if (n<=0) break; size+=(size_t)n; }
    close(fd[0]); int status=0; while (waitpid(pid,&status,0)<0 && errno==EINTR) {}
    if (WIFEXITED(status) && WEXITSTATUS(status)==0) { if (size && path[size-1]=='\n') size--; path[size]=0; }
    else { path[0]=0; if (WIFEXITED(status) && WEXITSTATUS(status)==127) snprintf(message,sizeof(message),"File picker unavailable. Paste a ROM path into the path field."); }
    return path;
}
long nes_preferences(const char *text) {
    char path[PATH_MAX];
    if (!storage_path(path,"state")) return 0;
    if (snprintf(path,sizeof(path),"%s/library.json",save_dir)>=PATH_MAX) return 0;
    return atomic_write(path,text,strlen(text));
}
