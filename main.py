import typing
import time
import sys

import pygame

from constants import TOTAL_MEM, SCREEN_RES_X, SCREEN_RES_Y, PIXEL_SCALE
from util import iter_bits


class Memory:
    def __init__(
        self,
        bytes_in: typing.Union[list[int], None] = None,
    ):
        if bytes_in == None:
            self.mem = [
                0,
            ] * TOTAL_MEM
        else:
            remaining = max(0, TOTAL_MEM - len(bytes_in) - 512)
            self.mem = (
                [
                    0,
                ]
                * 512
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

    def reset(self, mem: Memory):
        self.mem = mem
        self.pc = 512
        self.i = 0
        self.stack = Stack()
        self.delay = 0
        self.sound = 0

        self.tick = 0

        self.registers = [
            0,
        ] * 16

        self.reset_screen()

        self.surface = pygame.Surface((SCREEN_RES_X, SCREEN_RES_Y))

    def draw_screen(self):
        for y, _ in enumerate(self.screen_buff):
            for x, pix in enumerate(_):
                if not pix:
                    continue

                self.surface.set_at((x, y), "white")

    def step(self):
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

        match instr_type:
            case 0:
                if instr == 0x00E0:  # 00E0: clear screen
                    self.reset_screen()
            case 1:
                self.pc = immediate_address  # 1NNN: jump to NNN
            case 6:  # 6XNN: set register X to NN
                self.registers[x] = immediate_number
            case 7:  # 7XNN: add NN to register X
                self.registers[x] = (self.registers[x] + immediate_number) % 256
            case 10:
                self.i = immediate_address  # AXNN: set index register to NNN
            case 13:  # DXYN: display
                og_x_coord = self.registers[x] % SCREEN_RES_X
                x_coord = og_x_coord
                y_coord = self.registers[y] % SCREEN_RES_Y
                self.registers[15] = 0

                for row in range(n):
                    if y_coord >= SCREEN_RES_Y:
                        break

                    row_data = self.mem.read(self.i + row)
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
            case _:
                print(bin(instr))

        self.tick += 1


def main():
    if len(sys.argv) < 2:
        print("fuck you")
        sys.exit(1)

    fname = sys.argv[1]
    with open(fname, "rb") as handle:
        bytes_raw = handle.read()

    mem = Memory(list(bytes_raw))

    screen, clock = (
        pygame.display.set_mode(
            (SCREEN_RES_X * PIXEL_SCALE, SCREEN_RES_Y * PIXEL_SCALE)
        ),
        pygame.time.Clock(),
    )

    emu = Emulator(mem)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

        frame_start = time.perf_counter()

        for i in range(700 // 60):
            emu.step()

        frame_end = time.perf_counter()

        emu.draw_screen()

        pygame.transform.scale_by(emu.surface, PIXEL_SCALE, screen)
        pygame.display.flip()

        time.sleep((1 / 60) - (frame_end - frame_start))


if __name__ == "__main__":
    main()
