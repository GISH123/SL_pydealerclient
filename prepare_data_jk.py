import tensorflow as tf
import pathlib
# configuration.py from trainingtool
IMAGE_HEIGHT = 299
IMAGE_WIDTH = 299
CHANNELS = 3

def load_and_preprocess_image(image_raw, data_augmentation=False):
    # decode
    image = tf.io.decode_image(contents=image_raw, channels=CHANNELS, dtype=tf.dtypes.float32)
    

    if data_augmentation==False:
        image = tf.image.resize(image, [IMAGE_HEIGHT,IMAGE_WIDTH] )
        
       
    if data_augmentation==True:
        image = tf.image.resize(image, [IMAGE_HEIGHT,IMAGE_WIDTH] )
        image = tf.image.random_flip_left_right(image=image)
        image = tf.image.resize_with_crop_or_pad(image=image,
                                                 target_height=int(IMAGE_HEIGHT * 1.2 ),
                                                 target_width=int(IMAGE_WIDTH * 1.2) )
        
        
        image = tf.image.random_crop(value=image, size=[IMAGE_HEIGHT, IMAGE_WIDTH, CHANNELS])
        image = tf.image.random_brightness(image=image, max_delta=0.5)
        
        
    return image

