import typing
import time
import sys
import random

import pygame

pygame.init()
pygame.mixer.init()

from constants import (
    TOTAL_MEM,
    SCREEN_RES_X,
    SCREEN_RES_Y,
    PIXEL_SCALE,
    ORIGINAL_SHIFT_IMPL,
    ORIGINAL_JWO_IMPL,
    ORIGINAL_ATI_IMPL,
    ORIGINAL_GK_IMPL,
    ORIGINAL_STR_IMPL,
    KEY_CODES,
)
from util import iter_bits


class _MyBreak(Exception):
    pass


class Memory:
    def __init__(self, bytes_in: list[int], font_bytes: list[int]):
        remaining = max(0, TOTAL_MEM - len(bytes_in) - 512)
        remaining_fnt = max(0, 512 - len(font_bytes) - 0x50)

        self.mem = (
            [
                0,
            ]
            * 0x50
            + font_bytes
            + [
                0,
            ]
            * remaining_fnt
            + bytes_in
            + [
                0,
            ]
            * remaining
        )

    def read(self, i: int) -> int:
        return self.mem[i]

    def read_word(self, i: int) -> int:
        raw = self.mem[i : i + 2]

        return (raw[0] << 8) | raw[1]

    def write(self, i: int, val: int):
        self.mem[i] = val


class Stack:
    def __init__(self):
        self.arr = []

    def push(self, var):
        self.arr.append(var)

    def pop(self) -> typing.Any:
        return self.arr.pop()


class Emulator:
    def __init__(self, mem: Memory):
        self.reset(mem)

    def reset_screen(self):
        self.screen_buff = []
        for y in range(SCREEN_RES_Y):
            self.screen_buff.append([])
            for x in range(SCREEN_RES_X):
                self.screen_buff[y].append(0)

        self.surface = pygame.Surface((SCREEN_RES_X, SCREEN_RES_Y))

    def reset(self, mem: Memory):
        self.mem = mem
        self.pc = 512
        self.index = 0
        self.stack = Stack()
        self.delay = 0
        self.sound = 0
        self.key_pressed = False

        self.tick = 0

        self.registers = [
            0,
        ] * 16

        self.reset_screen()

    def draw_screen(self):
        for y, _ in enumerate(self.screen_buff):
            for x, pix in enumerate(_):
                if not pix:
                    continue

                self.surface.set_at((x, y), "white")

    def step(self, keys: list[bool]):
        instr = self.mem.read_word(self.pc)
        self.pc += 2

        nibs = [
            (instr & 0b1111000000000000) >> 12,
            (instr & 0b0000111100000000) >> 8,
            (instr & 0b0000000011110000) >> 4,
            (instr & 0b0000000000001111),
        ]

        instr_type = nibs[0]
        x = nibs[1]
        y = nibs[2]
        n = nibs[3]
        immediate_number = (nibs[2] << 4) | nibs[3]
        immediate_address = (nibs[1] << 8) | (nibs[2] << 4) | nibs[3]

        try:
            match instr_type:
                case 0:
                    if instr == 0x00E0:  # 00E0: clear screen
                        self.reset_screen()
                    elif instr == 0x00EE:  # 00EE: return from subroutine
                        self.pc = self.stack.pop()
                case 1:
                    self.pc = immediate_address  # 1NNN: jump to NNN
                case 2:
                    self.stack.push(self.pc)  # 2NNN: call subroutine at NNN
                    self.pc = immediate_address
                case 3:  # 3XNN: skip one instruction if register == num
                    if self.registers[x] == immediate_number:
                        self.pc += 2
                case 4:  # 4XNN: skip one instruction if register != num
                    if not self.registers[x] == immediate_number:
                        self.pc += 2
                case 5:  # 5XY0: skip one instruction if register X == register Y
                    if self.registers[x] == self.registers[y]:
                        self.pc += 2
                case 6:  # 6XNN: set register X to NN
                    self.registers[x] = immediate_number
                case 7:  # 7XNN: add NN to register X
                    self.registers[x] = (self.registers[x] + immediate_number) & 0xFF
                case 8:
                    match nibs[3]:
                        case 0:  # 8XY0: set register X to register Y
                            self.registers[x] = self.registers[y]
                        case 1:  # 8XY1: binary or register X and register Y, store in X
                            self.registers[x] |= self.registers[y]
                        case (
                            2
                        ):  # 8XY2: binary and register X and register Y, store in X
                            self.registers[x] &= self.registers[y]
                        case (
                            3
                        ):  # 8XY3: logical xor register X and register Y, store in X
                            self.registers[x] ^= self.registers[y]
                        case 4:  # 8XY4: add register X and register Y, store in X
                            tmp = self.registers[x] + self.registers[y]

                            self.registers[x] = tmp & 0xFF
                            self.registers[15] = int(tmp > 255)  # VF = carry bit
                        case (
                            5 | 7
                        ):  # 8XY5/7: subtract register X and register Y, store in X
                            a = self.registers[x] if nibs[3] == 5 else self.registers[y]
                            b = self.registers[y] if nibs[3] == 5 else self.registers[x]
                            tmp = a - b

                            self.registers[x] = tmp & 0xFF
                            self.registers[15] = int(a >= b)  # VF = carry bit
                        case 6:  # 8XY6: shift register X 1 bit right
                            if ORIGINAL_SHIFT_IMPL:
                                self.registers[x] = self.registers[y]

                            tmp = self.registers[x]
                            self.registers[x] >>= 1
                            self.registers[15] = tmp & 0b1  # VF = shifted out bit
                        case 0xE:  # 8XYE: shift register X 1 bit left
                            if ORIGINAL_SHIFT_IMPL:
                                self.registers[x] = self.registers[y]

                            tmp = self.registers[x]
                            self.registers[x] = (self.registers[x] << 1) & 0xFF
                            self.registers[15] = (
                                tmp & 0b10000000
                            ) >> 7  # VF = shifted out bit
                case 9:  # 9XY0: skip one instruction if register X != register Y
                    if not self.registers[x] == self.registers[y]:
                        self.pc += 2
                case 0xA:
                    self.index = immediate_address  # AXNN: set index register to NNN
                case 0xB:  # BXNN/BNNN: jump to NNN/XNN + register X/0
                    reg = self.registers[x]
                    if ORIGINAL_JWO_IMPL:
                        reg = self.registers[0]

                    self.pc = immediate_address + reg
                case (
                    0xC
                ):  # CXNN: random num between 0 and NN, binary and with register X
                    rand = random.randint(0, immediate_number)
                    self.registers[x] = rand & immediate_number
                case 0xD:  # DXYN: display
                    og_x_coord = self.registers[x] % SCREEN_RES_X
                    x_coord = og_x_coord
                    y_coord = self.registers[y] % SCREEN_RES_Y
                    self.registers[15] = 0

                    for row in range(n):
                        if y_coord >= SCREEN_RES_Y:
                            break

                        row_data = self.mem.read(self.index + row)
                        x_coord = og_x_coord
                        for bit in iter_bits(row_data):
                            if x_coord >= SCREEN_RES_X:
                                break

                            pix = self.screen_buff[y_coord][x_coord]

                            if bit and pix:
                                self.screen_buff[y_coord][x_coord] = 0
                                self.registers[15] = 1
                            if bit and not pix:
                                self.screen_buff[y_coord][x_coord] = 1

                            x_coord += 1
                        y_coord += 1
                case 0xE:
                    if nibs[2:4] == [
                        0x9,
                        0xE,
                    ]:  # EX9E: skip if key in register X is held down
                        if keys[self.registers[x]]:
                            self.pc += 2
                    elif nibs[2:4] == [
                        0xA,
                        0x1,
                    ]:  # EXA1: skip if key in register X is not held down
                        if not keys[self.registers[x]]:
                            self.pc += 2
                case 0xF:
                    match immediate_number:
                        case 0x07:  # FX07: set register X to delay timer
                            self.registers[x] = self.delay
                        case 0x15:  # FX15: set delay timer to register X
                            self.delay = self.registers[x]
                        case 0x18:  # FX18: set sound timer to register X
                            self.sound = self.registers[x]
                        case 0x1E:  # FX1E: add register X to index register
                            tmp = self.index + self.registers[x]

                            self.index = tmp
                            if tmp > TOTAL_MEM and not ORIGINAL_ATI_IMPL:
                                self.registers[15] = 1
                        case 0x0A:  # FX0A: block until key is pressed
                            if not any(keys) and not self.key_pressed:
                                self.pc -= 2
                                raise _MyBreak()
                            else:
                                if self.key_pressed is False:
                                    self.key_pressed = keys.index(True)
                                    self.registers[x] = self.key_pressed
                                if keys[self.key_pressed] and ORIGINAL_GK_IMPL:
                                    self.pc -= 2
                                    raise _MyBreak()
                                self.key_pressed = False
                        case 0x29:  # FX29: set index register to address of character
                            self.i = (
                                list("0123456789ABCDEF").index(
                                    hex(self.registers[x])[-1]
                                )
                                * 5
                                + 0x50
                            )
                        case 0x33:  # FX33: split register X into digits
                            digits = list(
                                map(int, list(str(self.registers[x])))
                            )  # evil fuckery
                            digits = [
                                0,
                            ] * (3 - len(digits)) + digits

                            for i, digit in enumerate(digits):
                                self.mem.write(self.index + i, digit)
                        case 0x55:  # FX55: write registers to memory at index
                            for i in range(x + 1):
                                self.mem.write(self.index + i, self.registers[i])

                            if ORIGINAL_STR_IMPL:
                                self.index += x + 1
                        case 0x65:  # FX65: load registers from memory at index
                            for i in range(x + 1):
                                self.registers[i] = self.mem.read(self.index + i)

                            if ORIGINAL_STR_IMPL:
                                self.index += x + 1
                case _:
                    print(bin(instr))
        except _MyBreak:
            pass

        self.tick += 1


def main():
    if len(sys.argv) < 4:
        print("fuck you")
        sys.exit(1)

    fname = sys.argv[1]
    with open(fname, "rb") as handle:
        bytes_raw = handle.read()

    ftname = sys.argv[2]
    with open(ftname, "r") as handle:
        font_bytes = [int(hexstr.strip(), 16) for hexstr in handle.readlines()]

    bpname = sys.argv[3]

    mem = Memory(list(bytes_raw), font_bytes)

    screen = pygame.display.set_mode(
        (SCREEN_RES_X * PIXEL_SCALE, SCREEN_RES_Y * PIXEL_SCALE)
    )

    beep = pygame.mixer.Sound(bpname)

    emu = Emulator(mem)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

        keys_raw = pygame.key.get_pressed()
        keys = [keys_raw[key_code] for key_code in KEY_CODES]

        for i in range(700 // 60):
            emu.step(keys)

        emu.draw_screen()

        pygame.transform.scale_by(emu.surface, PIXEL_SCALE, screen)
        pygame.display.flip()

        if emu.sound > 0 and not pygame.mixer.get_busy():
            beep.play()

        emu.delay = max(emu.delay - 1, 0)
        emu.sound = max(emu.sound - 1, 0)

        time.sleep((1 / 60))


if __name__ == "__main__":
    main()
