import { Config } from '@remotion/cli/config'

// H.264 in an MP4 plays everywhere; JPEG frames render faster than PNG for a flat design.
Config.setVideoImageFormat('jpeg')
Config.setCodec('h264')
Config.setCrf(23)
