import argparse
import os
import numpy as np

def convert(input, output, w, h, bpp, s):
    # Open input file for reading
    with open(input, "rb") as f:
        numpy_data = np.fromfile(f,dtype=np.uint8)
        size = int(s * h)
        if size == numpy_data.shape[0]:
            print(f"Input check passed. File size of {size} Bytes is correct");
        else:
            print(f"Input check failed. Expecting {size} Byte but file is {numpy_data.shape[0]} Bytes")
            return -1
    if bpp == 12:
        # Create 16-bit per pixel container for the image
        container = np.empty([w*h], dtype=np.uint16)
        # Valid Bytes per line
        valid_bpl = ((w + 1) // 2) * 3
        for row in range(h):
            # Two 12 bit pixels (A and B) are packed into 3 bytes
            #  byte 1   byte 2   byte 3
            # AAAAAAAA BBBBBBBB AAAABBBB
            # byte 1 and byte 2 each contains 8 MSB of pixel A and B
            # byte 3 contains 4 LSB of pixel A and B
            # Create a pointer to byte 1, which contains bit 4 to bit 11 of pixel A
            pA_b4_b11 = numpy_data[row*s:row*s+valid_bpl:3]
            # Create a pointer to byte 2, which contains bit 4 to bit 11 of pixel B
            pB_b4_b11 = numpy_data[row*s+1:row*s+valid_bpl:3]
            # Create a pointer to byte 3, which contains bit 0 to bit 3 of pixel A and pixel B
            pA_pB_lsb = numpy_data[row*s+2:row*s+valid_bpl:3]
            # Copy byte 1 and byte 2 to the 16-bit container, and shift the MSB.
            container[row*w:(row+1)*w:2] = pA_b4_b11[::].astype(np.uint16) << 4
            container[row*w+1:(row+1)*w:2] = pB_b4_b11[::].astype(np.uint16) << 4
            # Obtain the LSB of pixel A and B and add to the container.
            for byte in range(2):
                container[row*w+byte:(row+1)*w:2] |= ((pA_pB_lsb[::] >> (1 - byte) * 4) & 0b1111)
    elif bpp == 10:
        # Create 16-bit per pixel container for the image
        container = np.empty([w*h], dtype=np.uint16)
        # Valid Bytes per line
        valid_bpl = ((w + 3) // 4) * 5
        for row in range(h):
            # Four 10 bit pixels (A,B,C,D) are packed into 5 bytes
            #  byte 1   byte 2   byte 3   byte 4   byte 5
            # AAAAAAAA BBBBBBBB CCCCCCCC DDDDDDDD AABBCCDD
            # byte 1 to byte 4 each contains 8 MSB of pixel A,B,C,D
            # byte 5 contains 2 LSB of pixel A,B,C,D
            # Create a pointer to byte 1, which contains bit 2 to bit 9 of pixel A
            pA_b2_b9 = numpy_data[row*s:row*s+valid_bpl:5]
            # Create a pointer to byte 2, which contains bit 2 to bit 9 of pixel B
            pB_b2_b9 = numpy_data[row*s+1:row*s+valid_bpl:5]
            # Create a pointer to byte 3, which contains bit 2 to bit 9 of pixel C
            pC_b2_b9 = numpy_data[row*s+2:row*s+valid_bpl:5]
            # Create a pointer to byte 2, which contains bit 2 to bit 9 of pixel D
            pD_b2_b9 = numpy_data[row*s+3:row*s+valid_bpl:5]
            # Create a pointer to byte 4, which contains bit 0 to bit 1 of pixel A,B,C,D
            pA_pB_pC_pD_lsb = numpy_data[row*s+4:row*s+valid_bpl:5]
            # Copy byte 1 to byte 4 to the 16-bit container, and shift the MSB.
            container[row*w:(row+1)*w:4] = pA_b2_b9[::].astype(np.uint16) << 2
            container[row*w+1:(row+1)*w:4] = pB_b2_b9[::].astype(np.uint16) << 2
            container[row*w+2:(row+1)*w:4] = pC_b2_b9[::].astype(np.uint16) << 2
            container[row*w+3:(row+1)*w:4] = pD_b2_b9[::].astype(np.uint16) << 2
            # Obtain the LSB of pixel A,B,C,D and add to the container.
            for byte in range(4):
                container[row*w+byte:(row+1)*w:4] |= ((pA_pB_pC_pD_lsb[::] >> (3 - byte) * 2) & 0b11)
    elif bpp == 8:
        # Create 8-bit per pixel container for the image
        container = np.empty([w*h], dtype=np.uint8)
        # Valid Bytes per line
        valid_bpl = w
        for row in range(h):
            container[row*w:(row+1)*w:1] = numpy_data[row*s:row*s+valid_bpl:1]
    else:
        print(f"Only 8/10/12 bits per pixel input is supported.");
        exit(-1)
    # Open output file and write a PGM header
    with open(output, 'w') as f:
        f.write("P5\r")
        f.write(f"{str(w)} ")
        f.write(f"{str(h)}\r")
        f.write(f"{2**bpp-1}\r")
    # Swap bytes endianess, as pgm uses big endian and ImageJ as well.
    container.newbyteorder().byteswap(inplace=True)
    # Write the container to file
    with open(output, 'ab') as f:
        f.write(container)
    print(f"Output converted image to file {output}.");


if __name__ == "__main__":
    # Argument handling
    ap = argparse.ArgumentParser(description='Convert 12 bit pack RAW to 16 bit PGM.')
    ap.add_argument('-input', type=str, required=True, help='input: input image file.')
    ap.add_argument('-width', type=int, required=True, help='width: width of input image.')
    ap.add_argument('-height', type=int, required=True, help='height: height of input image.')
    ap.add_argument('-bpp', type=int, required=False, help='bpp: bits per pixe. Support 8, 10, 12.')
 
    args = vars(ap.parse_args())
    # Process -input
    arg_input = args['input'] 
    if not os.path.exists(arg_input) :
        print(f"ERROR: -input does not exist ({arg_input})")
        exit(-1)
    # Process -width
    arg_width = args['width']
    # Process -height
    arg_height = args['height']
    # Process -height
    arg_bpp = args['bpp']

    input = arg_input
    output = arg_input+".pgm"
    w = arg_width
    h = arg_height
    bpp = arg_bpp
    assert(bpp == 8 or bpp == 10 or bpp == 12), f"Only 8/10/12 bits per pixel input is supported."
    # calculate stride (Bytes per line)
    # Raspberry Pi hardware requires Bytes per line multiple of 32
    if bpp == 8:
        s = ((w + 31) // 32) * 32
    elif bpp == 10:
        s = ((((w + 3) // 4) * 5 + 31) // 32) * 32
    elif bpp == 12:
        s = ((((w + 1) // 2) * 3 + 31) // 32) * 32
    else:
        exit(-1);
    print(f"Input image stride is configured to be {s}")
    convert(input, output, w, h, bpp, s)

