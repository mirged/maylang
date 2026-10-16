/* Optional blargg test-ROM harness; ROM files are supplied separately. */
#include "emulator.h"
#include <assert.h>
#include <stdio.h>
static void input(SystemInput *in,void *u,bool s) { (void)u;(void)s;memset(in,0,sizeof(*in)); }
int main(int argc, char **argv) {
    FileData rom={0}; assert(argc==2); assert(file_read(argv[1],&rom)==OK);
    EmulatorInit init={.rom=rom,.audio_frequency=48000,.audio_frames=512,.ram_init=RAM_INIT_ZERO};
    Emulator *e=emulator_new(&init); assert(e); emulator_set_joypad_callback(e,input,NULL);
    for (int f=0; f<30000; f++) {
        Ticks limit=emulator_get_ticks(e)+e->master_ticks_per_frame;
        EmulatorEvent event;
        do { event=emulator_run_until(e,limit); assert(!(event&EMULATOR_EVENT_INVALID_OPCODE)); } while(!(event&EMULATOR_EVENT_UNTIL_TICKS));
        u8 *ram=e->prg_ram_map;
        if (ram[1]==0xde && ram[2]==0xb0 && ram[3]==0x61 && ram[0]<0x80) {
            printf("CPU test status=%d after %d frames: %s\n",ram[0],f,ram+4);
            int status=ram[0]; emulator_delete(e);file_data_delete(&rom);return status;
        }
    }
    puts("CPU test timeout");return 1;
}
