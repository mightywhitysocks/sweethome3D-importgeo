package com.eteks.sweethome3d.utilities;

import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;
import org.sunflow.system.UI;
import org.sunflow.system.ui.ConsoleInterface;
import com.eteks.sweethome3d.io.HomeFileRecorder;
import com.eteks.sweethome3d.j3d.PhotoRenderer;
import com.eteks.sweethome3d.model.Camera;
import com.eteks.sweethome3d.model.Home;
import com.eteks.sweethome3d.model.HomeEnvironment;

/**
 * Rendu photo hors-ligne (headless) d'un .sh3d via le moteur SunFlow de Sweet
 * Home 3D (com.eteks.sweethome3d.j3d.PhotoRenderer) -- la meme brique que
 * "Creer photo" dans l'appli, appelee ici sans interface graphique.
 *
 * Adapte de com.eteks.sweethome3d.utilities.ConsolePhotoGenerator (Emmanuel
 * PUYBARET / eTeks, GPLv2) -- cette classe n'existe PAS dans SweetHome3D.jar :
 * comme Conv.java, c'est un petit helper source compile contre le jar.
 *
 *   java [-Drender.quality=low|high] -Dj3d.rend=noop
 *        -cp SweetHome3D.jar;sunflow.jar;j3dcore.jar;vecmath.jar;j3dutils.jar;
 *            batik-svgpathparser.jar;<cls>
 *        com.eteks.sweethome3d.utilities.RenderPhoto
 *        <in.sh3d> <out.png> [largeur] [hauteur] [x y z yaw pitch [fov]]
 *
 * Sans x/y/z/yaw/pitch : la camera enregistree dans le .sh3d. Avec : un point de
 * vue arbitraire (repere plan Sweet Home 3D, cm ; angles en radians).
 * -Drender.quality force LOW (rapide) ou HIGH ; defaut = qualite du .sh3d.
 *
 * IMPORTANT (Linux) : meme avec -Dj3d.rend=noop, Java3D interroge un
 * GraphicsEnvironment au demarrage -> lancer sous xvfb-run. Inutile sous Windows.
 */
public class RenderPhoto {
  public static void main(String[] args) throws Exception {
    String homeFile = args[0];
    String outPng = args[1];
    int width = args.length > 2 ? Integer.parseInt(args[2]) : 1024;
    int height = args.length > 3 ? Integer.parseInt(args[3]) : 768;

    Home home = new HomeFileRecorder().readHome(homeFile);
    HomeEnvironment environment = home.getEnvironment();

    String q = System.getProperty("render.quality", "");
    PhotoRenderer.Quality quality =
        q.equalsIgnoreCase("low") ? PhotoRenderer.Quality.LOW
        : q.equalsIgnoreCase("high") ? PhotoRenderer.Quality.HIGH
        : (environment.getPhotoQuality() >= 3 ? PhotoRenderer.Quality.HIGH
                                              : PhotoRenderer.Quality.LOW);
    PhotoRenderer renderer = new PhotoRenderer(home, quality);

    Camera camera;
    if (args.length >= 9) {
      float fov = args.length > 9 ? Float.parseFloat(args[9]) : 1.0995575f;
      camera = new Camera(Float.parseFloat(args[4]), Float.parseFloat(args[5]),
          Float.parseFloat(args[6]), Float.parseFloat(args[7]),
          Float.parseFloat(args[8]), fov);
    } else {
      camera = home.getCamera();
    }

    UI.set(new ConsoleInterface());
    BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
    renderer.render(image, camera, null);
    ImageIO.write(image, outPng.substring(outPng.lastIndexOf('.') + 1), new File(outPng));
    System.out.println("ecrit : " + outPng + "  (" + width + "x" + height + ", " + quality + ")");
  }
}