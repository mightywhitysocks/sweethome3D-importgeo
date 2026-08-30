package com.eteks.sweethome3d.utilities;

import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;
import org.sunflow.system.UI;
import org.sunflow.system.ui.ConsoleInterface;
import com.eteks.sweethome3d.io.HomeFileRecorder;
import com.eteks.sweethome3d.j3d.PhotoRenderer;
import com.eteks.sweethome3d.model.Home;
import com.eteks.sweethome3d.model.HomeEnvironment;

/**
 * Rendu photo hors-ligne (headless) d'un .sh3d via le moteur SunFlow de Sweet
 * Home 3D (com.eteks.sweethome3d.j3d.PhotoRenderer) — la meme brique que
 * "Creer photo" qualite 3/4 dans l'appli, appelee ici sans interface graphique.
 *
 * Adapte de com.eteks.sweethome3d.utilities.ConsolePhotoGenerator (Emmanuel
 * PUYBARET / eTeks, GPLv2) — cette classe n'existe PAS dans SweetHome3D.jar :
 * comme Conv.java, c'est un petit helper source compile contre le jar.
 *
 *   java -Dj3d.rend=noop -cp SweetHome3D.jar;sunflow.jar;j3dcore.jar;vecmath.jar;
 *        j3dutils.jar;batik-svgpathparser.jar;<cls>
 *        com.eteks.sweethome3d.utilities.RenderPhoto <in.sh3d> <out.png> [largeur] [hauteur]
 *
 * IMPORTANT (Linux) : meme avec -Dj3d.rend=noop (pipeline GPU desactive),
 * Java3D interroge un GraphicsEnvironment au demarrage -> sans serveur X reel
 * ou virtuel, VirtualUniverse leve HeadlessException. Lancer sous xvfb-run.
 * Non necessaire sous Windows.
 */
public class RenderPhoto {
  public static void main(String[] args) throws Exception {
    String homeFile = args[0];
    String outPng = args[1];
    int width = args.length > 2 ? Integer.parseInt(args[2]) : 1024;
    int height = args.length > 3 ? Integer.parseInt(args[3]) : 768;

    Home home = new HomeFileRecorder().readHome(homeFile);
    HomeEnvironment environment = home.getEnvironment();
    PhotoRenderer renderer = new PhotoRenderer(home,
        environment.getPhotoQuality() == 3
            ? PhotoRenderer.Quality.HIGH
            : PhotoRenderer.Quality.LOW);
    UI.set(new ConsoleInterface());
    BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
    renderer.render(image, home.getCamera(), null);
    ImageIO.write(image, outPng.substring(outPng.lastIndexOf('.') + 1), new File(outPng));
    System.out.println("ecrit : " + outPng + "  (" + width + "x" + height + ")");
  }
}
