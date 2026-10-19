/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef GA107_TARGET_H
#define GA107_TARGET_H
#define GA107_PCI_ID 0x25ab
/* Only the user's LG board; other GA107 SKUs remain excluded. */
static inline int ga107_board_matches(unsigned int vendor, unsigned int device,
                                     unsigned int subvendor, unsigned int subdevice)
{
    return vendor == 0x10de && device == GA107_PCI_ID &&
           subvendor == 0x1854 && subdevice == 0x052f;
}
#endif
