import jsQR from 'jsqr';
if(window.yamDesktop)window.prompt=(message,defaultValue='')=>window.yamDesktop.prompt(message,defaultValue);
// The existing scanner uses BarcodeDetector, which Chromium does not expose on all Windows PCs.
if(window.yamDesktop&&!('BarcodeDetector' in window)) {
  window.BarcodeDetector=class {
    static async getSupportedFormats(){return ['qr_code'];}
    constructor(){this.canvas=document.createElement('canvas');this.context=this.canvas.getContext('2d',{willReadFrequently:true});}
    async detect(source){
      const w=source.videoWidth||source.width,h=source.videoHeight||source.height;
      if(!w||!h)return [];
      const scale=Math.min(1,960/w);this.canvas.width=Math.round(w*scale);this.canvas.height=Math.round(h*scale);
      this.context.drawImage(source,0,0,this.canvas.width,this.canvas.height);
      const image=this.context.getImageData(0,0,this.canvas.width,this.canvas.height);
      const result=jsQR(image.data,image.width,image.height,{inversionAttempts:'attemptBoth'});
      return result?[{rawValue:result.data,format:'qr_code'}]:[];
    }
  };
}
