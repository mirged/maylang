#include <assert.h>
long nes_load(const char *);
long nes_frame(long);
long nes_save(void);
long nes_restore(void);
void nes_close(void);
int main(void) {
    for (int i=0; i<12; i++) {
        assert(nes_load(""));
        for (int f=0; f<90; f++) assert(nes_frame(f<45 ? 128 : 64));
        assert(nes_save()); assert(nes_frame(1)); assert(nes_restore());
    }
    nes_close(); return 0;
}
