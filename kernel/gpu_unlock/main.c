// SPDX-License-Identifier: GPL-2.0-only
#include <linux/init.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/string.h>
#include "target.h"
#include "unlock_610.h"

static char *target;
static bool execute;
module_param(target, charp, 0444);
MODULE_PARM_DESC(target, "Exact full PCI address; no all/list support");
module_param(execute, bool, 0444);
MODULE_PARM_DESC(execute, "Run unverified GA107 V67/SS0 experiment (default false)");

static int __init ga107_unlock_init(void)
{
    struct pci_dev *pdev = NULL;
    struct gpu_unlock_610_shared shared = {0};
    int ret;
    if (!target || !*target) {
        pr_info("ga107_unlock: disabled; no target specified\n");
        return 0;
    }
    while ((pdev = pci_get_device(PCI_VENDOR_ID_NVIDIA, GA107_PCI_ID, pdev))) {
        if (strcmp(pci_name(pdev), target))
            continue;
        if (!ga107_board_matches(pdev->vendor, pdev->device,
                                pdev->subsystem_vendor, pdev->subsystem_device)) {
            pci_err(pdev, "ga107_unlock: LG 1854:052f board required\n");
            pci_dev_put(pdev);
            return -ENODEV;
        }
        if (!execute) {
            pci_info(pdev, "ga107_unlock: matched; execute=0, no firmware request or MMIO\n");
            pci_dev_put(pdev);
            return 0;
        }
        pci_dev_lock(pdev);
        if (pdev->driver) {
            pci_err(pdev, "ga107_unlock: bound card refused; cold pre-driver boot required\n");
            pci_dev_unlock(pdev);
            pci_dev_put(pdev);
            return -EBUSY;
        }
        pci_warn(pdev, "ga107_unlock: EXPERIMENTAL V67 + SS0; SS1 preserved; performance unverified\n");
        ret = gpu_unlock_610_load_shared(pdev, &shared);
        if (!ret)
            ret = gpu_unlock_610_unlock(pdev, &shared);
        gpu_unlock_610_release_shared(&shared);
        pci_dev_unlock(pdev);
        if (ret)
            pci_err(pdev, "ga107_unlock: experiment failed (%d); power off before retry\n", ret);
        else
            pci_info(pdev, "ga107_unlock: SS0 applied and FLR completed; benchmark required\n");
        pci_dev_put(pdev);
        /* After hardware work init must succeed: a failed transaction may
         * retain DMA buffers and pin THIS_MODULE until full power removal. */
        return 0;
    }
    pr_err("ga107_unlock: no eligible GA107 at %s\n", target);
    return -ENODEV;
}
static void __exit ga107_unlock_exit(void) {}
module_init(ga107_unlock_init);
module_exit(ga107_unlock_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Experimental LG GA107 pre-driver V67/SS0 rate override");
MODULE_VERSION("0.1.1-experimental");
