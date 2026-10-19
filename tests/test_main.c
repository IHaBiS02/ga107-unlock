// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include "../kernel/gpu_unlock/main.c"

static struct pci_dev card;
static int loads, unlocks, releases;
void test_log(const struct pci_dev *p, const char *fmt, ...) { (void)p; (void)fmt; }
struct pci_dev *pci_get_device(unsigned int v, unsigned int d, struct pci_dev *from)
{
    if (from) { pci_dev_put(from); return NULL; }
    if (card.vendor != v || card.device != d) return NULL;
    return pci_dev_get(&card);
}
struct pci_dev *pci_dev_get(struct pci_dev *p) { p->refs++; return p; }
void pci_dev_put(struct pci_dev *p) { p->refs--; }
void pci_dev_lock(struct pci_dev *p) { assert(!p->locked); p->locked=true; }
void pci_dev_unlock(struct pci_dev *p) { assert(p->locked); p->locked=false; }
int gpu_unlock_610_load_shared(struct pci_dev *p, struct gpu_unlock_610_shared *s)
{ assert(p->locked); loads++; s->gsp=(void *)1; return 0; }
void gpu_unlock_610_release_shared(struct gpu_unlock_610_shared *s)
{ assert(s->gsp); releases++; s->gsp=NULL; }
int gpu_unlock_610_unlock(struct pci_dev *p, const struct gpu_unlock_610_shared *s)
{ assert(p->locked && !p->driver && s->gsp); unlocks++; return -EIO; }

int main(void)
{
    for(int scenario=0; scenario<9; scenario++) {
        card=(struct pci_dev){.name="0000:01:00.0", .vendor=0x10de,
            .device=0x25ab,.subsystem_vendor=0x1854,.subsystem_device=0x052f,.refs=1};
        target="0000:01:00.0"; execute=false; loads=unlocks=releases=0;
        if(scenario==0)target=NULL;
        if(scenario==2)target="all";
        if(scenario==3)target="0000:01:00.0,0000:02:00.0";
        if(scenario==4)card.subsystem_device=0x0530;
        if(scenario==5){execute=true;card.driver=&card;}
        if(scenario==6)card.device=0x2204;
        if(scenario==7)execute=true;
        if(scenario==8)target="0000:02:00.0";
        int ret=test_module_init();
        assert(ret==((scenario>=2 && scenario<=4) || scenario==6 || scenario==8 ?
                     -ENODEV:scenario==5?-EBUSY:0));
        assert(loads==(scenario==7) && unlocks==loads && releases==loads);
        assert(card.refs==1 && !card.locked);
    }
    puts("GA107 opt-in, BDF, board, bound-device and retained-failure entry checks passed");
}
